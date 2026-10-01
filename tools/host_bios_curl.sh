#!/bin/sh
# Host BIOS version AND release date, straight from the vSphere SOAP API.
#   . ~/vcenter.env  &&  sh bios_curl.sh
# Needs VC_HOST, VC_USER, VC_PASS. Read-only: Login, CreateContainerView,
# RetrievePropertiesEx, Logout.
set -e
: "${VC_HOST:?set VC_HOST}" "${VC_USER:?set VC_USER}" "${VC_PASS:?set VC_PASS}"
JAR=$(mktemp); trap 'rm -f "$JAR"' EXIT
SOAP='Content-Type: text/xml; charset=utf-8'
ACT='SOAPAction: urn:vim25/8.0.0.0'
URL="https://${VC_HOST}/sdk"

# 1. Login. The moid "SessionManager" is a fixed well-known identifier.
curl -sk -c "$JAR" -H "$SOAP" -H "$ACT" "$URL" --data-binary @- >/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" xmlns:v="urn:vim25">
 <s:Body><v:Login>
  <v:_this type="SessionManager">SessionManager</v:_this>
  <v:userName>${VC_USER}</v:userName>
  <v:password>${VC_PASS}</v:password>
 </v:Login></s:Body></s:Envelope>
EOF

# 2. One view over every HostSystem. "group-d1" is the fixed root folder moid.
VIEW=$(curl -sk -b "$JAR" -c "$JAR" -H "$SOAP" -H "$ACT" "$URL" --data-binary @- <<'EOF' |
<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" xmlns:v="urn:vim25">
 <s:Body><v:CreateContainerView>
  <v:_this type="ViewManager">ViewManager</v:_this>
  <v:container type="Folder">group-d1</v:container>
  <v:type>HostSystem</v:type>
  <v:recursive>true</v:recursive>
 </v:CreateContainerView></s:Body></s:Envelope>
EOF
sed -n 's:.*<returnval type="ContainerView">\([^<]*\)</returnval>.*:\1:p')

# 3. Every host's name and full biosInfo in one round trip.
curl -sk -b "$JAR" -H "$SOAP" -H "$ACT" "$URL" --data-binary @- <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:v="urn:vim25">
 <s:Body><v:RetrievePropertiesEx>
  <v:_this type="PropertyCollector">propertyCollector</v:_this>
  <v:specSet>
   <v:propSet><v:type>HostSystem</v:type><v:all>false</v:all>
    <v:pathSet>name</v:pathSet>
    <v:pathSet>hardware.biosInfo</v:pathSet>
   </v:propSet>
   <v:objectSet>
    <v:obj type="ContainerView">${VIEW}</v:obj>
    <v:skip>true</v:skip>
    <v:selectSet xsi:type="v:TraversalSpec">
     <v:name>viewToHost</v:name><v:type>ContainerView</v:type>
     <v:path>view</v:path><v:skip>false</v:skip>
    </v:selectSet>
   </v:objectSet>
  </v:specSet>
  <v:options/>
 </v:RetrievePropertiesEx></s:Body></s:Envelope>
EOF

# 4. Always log out; vCenter keeps sessions alive otherwise.
curl -sk -b "$JAR" -H "$SOAP" -H "$ACT" "$URL" --data-binary @- >/dev/null <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" xmlns:v="urn:vim25">
 <s:Body><v:Logout><v:_this type="SessionManager">SessionManager</v:_this></v:Logout></s:Body>
</s:Envelope>
EOF
