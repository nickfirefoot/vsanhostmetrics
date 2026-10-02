# Screenshots

Drop dashboard screenshots here and the top-level README references them with
relative paths, which GitHub renders on the repository front page.

## Naming

One file per dashboard, lowercase, matching the dashboard name:

```
rapid-vsan-overview.png
rapid-vsan-network.png
rapid-vsan-storage.png
rapid-vsan-dom.png
rapid-vsan-resync.png
rapid-vsan-esa-write-path.png
rapid-vsan-host-resources.png
```

Anything else is free-form, prefixed by what it shows: `install-`, `view-`,
`adapter-`.

## Before committing

**These are permanent.** A screenshot removed in a later commit stays in the
git history and on anyone's clone. Check what is legible in each one:

- hostnames and cluster names
- management IP addresses
- the account in the top-right user menu
- anything in a browser tab, bookmark bar or notification

The lab is rebuilt regularly so its names are low-stakes, but that is a
judgement to make deliberately rather than by not looking.

## Keep them reasonable

Full-page PNGs run 200-400 KB. A dozen is fine in a repository this size
(1.5 MiB packed today). If they start running to megabytes, crop to the panel
that matters rather than capturing the whole browser: a screenshot of one table
is more useful documentation than a screenshot of a whole screen anyway.

## The alternative, when you do not want binaries in the repository

Drag an image into any GitHub issue or pull request comment. GitHub uploads it
and gives you a permanent CDN URL you can paste into Markdown. The image never
enters the repository, and the URL works in release notes, where relative paths
do not. Worth using for release notes specifically.
