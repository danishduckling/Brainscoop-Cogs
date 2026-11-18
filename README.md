# Brain Scoop Cogs

Red cogs developed for, or adapted for use by, The Brain Scoop Discord community.
Each cog is maintained as its own package so cogs can be installed and updated
independently.

## Install

Make sure Red's Downloader cog is available, then add this repository:

```text
[p]repo add brainscoop-cogs https://github.com/danishduckling/Brainscoop-Cogs
[p]cog install brainscoop-cogs MusicLeague
[p]load MusicLeague
```

To install the modified ExtendedModLog cog instead:

```text
[p]cog install brainscoop-cogs extendedmodlog
[p]load extendedmodlog
```

The repository does not need to be listed in Red's public index to be added by
its Git URL.

## Cogs

| Package | Status | Notes |
| --- | --- | --- |
| `MusicLeague` | Under development | Server-specific cog scaffold; `/musicleague` provides an ephemeral status response. |
| `extendedmodlog` | Fork | Modified from [TrustyJAID/Trusty-cogs](https://github.com/TrustyJAID/Trusty-cogs/tree/master/extendedmodlog). The upstream authors and license are retained. |

Installing a cog does not mean it is feature-complete. Check its cog information
and release notes before enabling it on a production bot.

## Adding a cog

Create a top-level package directory for each cog. Include an `__init__.py`
with an async `setup(bot)` entry point, the cog's Python module(s), and a
package-level `info.json`. Keep dependencies and files needed by that cog
inside its package where practical, so it remains independently installable.

Update the root `info.json` only for repository-wide information. For a fork,
retain its upstream attribution and license, and describe the upstream source
and local changes in this README and the cog's metadata.
