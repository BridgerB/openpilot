# MetaDrive Setup Guide

This guide documents how to get the full MetaDrive simulator running standalone on macOS with the openpilot nix development environment.

## Prerequisites

- macOS (tested on Apple Silicon)
- Nix package manager installed
- This openpilot repo with the `flake.nix` development environment

## Overview

openpilot includes a minimal MetaDrive integration in `tools/sim/bridge/metadrive/`. This guide sets up the **full** upstream MetaDrive simulator from [metadriverse/metadrive](https://github.com/metadriverse/metadrive) for standalone testing and development.

## Setup Steps

### Step 1: Clone the Full MetaDrive Repository

Clone the full MetaDrive repo into the bridge directory:

```bash
cd /Users/bridger/Developer/openpilot/tools/sim/bridge
git clone git@github.com:metadriverse/metadrive.git metadrive_full
```

This creates `tools/sim/bridge/metadrive_full/` alongside the existing minimal `metadrive/` integration.

### Step 2: Enter the Nix Development Shell

```bash
cd /Users/bridger/Developer/openpilot
nix develop
```

You should see:
```
openpilot development shell activated

Python: Python 3.12.12
uv: uv 0.9.26
```

### Step 3: Create a Virtual Environment for MetaDrive

The nix environment uses an immutable Python, so we need a separate venv for MetaDrive's dependencies:

```bash
cd /Users/bridger/Developer/openpilot/tools/sim/bridge/metadrive_full
uv venv .venv
```

### Step 4: Install MetaDrive in Editable Mode

**Important:** You must specify the venv's Python explicitly because `uv pip` defaults to the nix Python which is read-only:

```bash
uv pip install -e . --python .venv/bin/python
```

This installs MetaDrive and all its dependencies (~51 packages) including:
- panda3d (3D rendering engine)
- gymnasium (RL environment interface)
- numpy, opencv-python, pygame, etc.

On first run, MetaDrive will also download its assets (~200MB) from GitHub releases.

### Step 5: Run MetaDrive

**Critical:** You must run from a directory that does NOT have a subfolder called `metadrive`. Running from inside `metadrive_full/` or from `tools/sim/bridge/` will cause import errors.

```bash
cd /tmp
/Users/bridger/Developer/openpilot/tools/sim/bridge/metadrive_full/.venv/bin/python -m metadrive.examples.drive_in_single_agent_env
```

Or create an alias for convenience:
```bash
alias metadrive='/Users/bridger/Developer/openpilot/tools/sim/bridge/metadrive_full/.venv/bin/python -m'
cd /tmp
metadrive metadrive.examples.drive_in_single_agent_env
```

## Keyboard Controls

Once MetaDrive launches, you can drive manually:

| Key | Action |
|-----|--------|
| W | Accelerate |
| S | Brake |
| A | Steer Left |
| D | Steer Right |
| R | Reset Environment |
| Q | Third-person Camera |
| B | Top-down Camera |
| +/- | Raise/Lower Camera |
| F | Toggle FPS limit |
| H | Help |
| Esc | Quit |

## Available Examples

MetaDrive includes many example scripts:

```bash
cd /tmp
PYTHON=/Users/bridger/Developer/openpilot/tools/sim/bridge/metadrive_full/.venv/bin/python

# Single agent driving (default)
$PYTHON -m metadrive.examples.drive_in_single_agent_env

# Safe driving with obstacles
$PYTHON -m metadrive.examples.drive_in_safe_metadrive_env

# Multi-agent environments
$PYTHON -m metadrive.examples.drive_in_multi_agent_env --env roundabout
$PYTHON -m metadrive.examples.drive_in_multi_agent_env --env intersection
$PYTHON -m metadrive.examples.drive_in_multi_agent_env --env tollgate
$PYTHON -m metadrive.examples.drive_in_multi_agent_env --env bottleneck
$PYTHON -m metadrive.examples.drive_in_multi_agent_env --env parkinglot

# Real-world scenarios (nuScenes/Waymo)
$PYTHON -m metadrive.examples.drive_in_real_env
$PYTHON -m metadrive.examples.drive_in_real_env --waymo

# Top-down view
$PYTHON -m metadrive.examples.top_down_metadrive

# LiDAR point cloud visualization
$PYTHON -m metadrive.examples.point_cloud_lidar

# Performance profiling
$PYTHON -m metadrive.examples.profile_metadrive
```

## Basic Python Usage

```python
from metadrive.envs.metadrive_env import MetaDriveEnv

env = MetaDriveEnv(config={"use_render": True})
obs, info = env.reset()

for i in range(1000):
    obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
    if terminated or truncated:
        env.reset()

env.close()
```

## Troubleshooting

### "ImportError: cannot import name 'MetaDriveEnv' from 'metadrive'"

You're running from a directory that has a `metadrive` subfolder. Change to `/tmp` or another clean directory.

### "pip: command not found" or "externally managed environment"

Use `uv pip install -e . --python .venv/bin/python` instead of plain `pip install`.

### Assets download fails

MetaDrive downloads ~200MB of assets on first run. If it fails, you can manually download from:
https://github.com/metadriverse/metadrive/releases

Extract to `metadrive_full/metadrive/assets/`

### Virtual environment already exists

If you need to recreate the venv:
```bash
cd /Users/bridger/Developer/openpilot/tools/sim/bridge/metadrive_full
rm -rf .venv
uv venv .venv
uv pip install -e . --python .venv/bin/python
```

## Quick Reference

```bash
# One-liner to run MetaDrive (from nix develop shell)
cd /tmp && /Users/bridger/Developer/openpilot/tools/sim/bridge/metadrive_full/.venv/bin/python -m metadrive.examples.drive_in_single_agent_env
```

## Next Steps

- Integrate full MetaDrive with openpilot's bridge (see `tools/sim/bridge/metadrive/`)
- Test openpilot engagement with MetaDrive traffic scenarios
- Explore MetaDrive's RL training capabilities

## References

- [MetaDrive Documentation](https://metadrive-simulator.readthedocs.io)
- [MetaDrive GitHub](https://github.com/metadriverse/metadrive)
- [MetaDrive Paper](https://arxiv.org/pdf/2109.12674.pdf)
