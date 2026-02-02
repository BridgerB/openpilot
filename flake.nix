# flake.nix
{
  description = "openpilot development environment";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = {
    self,
    nixpkgs,
    pyproject-nix,
    uv2nix,
    pyproject-build-systems,
    ...
  }: let
    inherit (nixpkgs) lib;

    # Support macOS (both Intel and Apple Silicon) and Linux
    systems = ["x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin"];
    forAllSystems = lib.genAttrs systems;

    # Load the uv workspace
    workspace = uv2nix.lib.workspace.loadWorkspace {workspaceRoot = ./.;};

    # Create overlay from workspace - prefer wheels for easier builds
    overlay = workspace.mkPyprojectOverlay {
      sourcePreference = "wheel";
    };

    # Editable overlay for development
    editableOverlay = workspace.mkEditablePyprojectOverlay {
      root = "$REPO_ROOT";
    };

    # Packages that need setuptools as a build dependency but don't declare it
    needsSetuptools = [
      "mouseinfo"
      "progressbar"
      "pyautogui"
      "pygetwindow"
      "pyprof2calltree"
      "pyrect"
      "pyscreeze"
      "pytest-xdist"
      "pytweening"
    ];

    # Override for packages that need build dependencies not declared in metadata
    buildSystemOverrides = pkgs: final: prev:
      # Add setuptools to packages that need it
      lib.genAttrs needsSetuptools (name:
        prev.${name}.overrideAttrs (old: {
          nativeBuildInputs = (old.nativeBuildInputs or []) ++ [final.setuptools];
        }))
      // {
        # pyaudio needs setuptools + portaudio native library
        pyaudio = prev.pyaudio.overrideAttrs (old: {
          nativeBuildInputs = (old.nativeBuildInputs or []) ++ [final.setuptools];
          buildInputs = (old.buildInputs or []) ++ [pkgs.portaudio];
        });
        # openpilot needs editables for hatchling editable builds
        openpilot = prev.openpilot.overrideAttrs (old: {
          nativeBuildInputs = (old.nativeBuildInputs or []) ++ [final.editables];
        });
      };

    # Build Python package sets for each system
    pythonSets = forAllSystems (
      system: let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;
      in
        (pkgs.callPackage pyproject-nix.build.packages {
          inherit python;
        })
        .overrideScope (
          lib.composeManyExtensions [
            pyproject-build-systems.overlays.wheel
            overlay
            (buildSystemOverrides pkgs)
          ]
        )
    );

    # Native dependencies needed for openpilot
    nativeDeps = pkgs:
      with pkgs;
        [
          # Build tools
          git
          git-lfs
          gnumake
          cmake
          pkg-config
          scons

          # Compilers
          gcc
          llvmPackages.clang
          llvmPackages.llvm

          # ARM cross-compiler (for panda firmware)
          gcc-arm-embedded

          # Core libraries
          capnproto
          eigen
          zeromq
          cppzmq
          openssl_3
          libusb1
          libtool
          coreutils

          # Media
          ffmpeg
          portaudio

          # Graphics/UI
          glfw
          qt5.qtbase
          qt5.qttools
          qt5.qtserialbus
          qt5.qtcharts

          # OpenCL
          ocl-icd
          opencl-headers

          # uv for package management
          uv
        ]
        ++ lib.optionals pkgs.stdenv.isLinux [
          pocl
        ]
        ++ lib.optionals pkgs.stdenv.isDarwin [
          pkgs.apple-sdk_15
        ];
  in {
    devShells = forAllSystems (
      system: let
        pkgs = nixpkgs.legacyPackages.${system};
        pythonSet = pythonSets.${system}.overrideScope editableOverlay;

        # Create virtual environment with all dependencies
        virtualenv = pythonSet.mkVirtualEnv "openpilot-dev-env" workspace.deps.all;
      in {
        default = pkgs.mkShell {
          packages =
            [
              virtualenv
              pkgs.python312Packages.pygame
            ]
            ++ nativeDeps pkgs;

          env = {
            # Prevent uv from managing the virtualenv (handled by nix)
            UV_NO_SYNC = "1";
            UV_PYTHON = pythonSet.python.interpreter;
            UV_PYTHON_DOWNLOADS = "never";
          };

          shellHook = ''
            # Unset PYTHONPATH to avoid conflicts
            unset PYTHONPATH

            # Set repo root for editable installs
            export REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
            export OPENPILOT_ROOT="$REPO_ROOT"

            # Include/library paths for C/C++ compilation
            export C_INCLUDE_PATH="${pkgs.zeromq}/include:${pkgs.cppzmq}/include:${pkgs.capnproto}/include:${pkgs.eigen}/include:${pkgs.libusb1.dev}/include:${pkgs.openssl_3.dev}/include:${pkgs.ffmpeg.dev}/include:${pkgs.curl.dev}/include:${pkgs.bzip2.dev}/include:${pkgs.qt5.qtbase.dev}/include:${pkgs.qt5.qtbase.dev}/include/QtCore:${pkgs.qt5.qtbase.dev}/include/QtWidgets:${pkgs.qt5.qtbase.dev}/include/QtGui:${pkgs.qt5.qtbase.dev}/include/QtNetwork:${pkgs.qt5.qtbase.dev}/include/QtConcurrent:${pkgs.qt5.qtserialbus.dev}/include:${pkgs.qt5.qtcharts.dev}/include''${C_INCLUDE_PATH:+:$C_INCLUDE_PATH}"
            export CPLUS_INCLUDE_PATH="$C_INCLUDE_PATH"
            export LIBRARY_PATH="${pkgs.zeromq}/lib:${pkgs.capnproto}/lib:${pkgs.libusb1}/lib:${pkgs.openssl_3.out}/lib:${pkgs.ffmpeg.lib}/lib:${pkgs.curl.out}/lib:${pkgs.bzip2.out}/lib:${pkgs.ncurses}/lib:${pkgs.qt5.qtbase.out}/lib:${pkgs.qt5.qtserialbus.out}/lib:${pkgs.qt5.qtcharts.out}/lib''${LIBRARY_PATH:+:$LIBRARY_PATH}"

            # For scons to find libraries
            export PKG_CONFIG_PATH="${pkgs.zeromq}/lib/pkgconfig:${pkgs.capnproto}/lib/pkgconfig:${pkgs.openssl_3.dev}/lib/pkgconfig''${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"

            # Override CPPFLAGS/LDFLAGS for builds that respect them
            export CPPFLAGS="-I${pkgs.zeromq}/include -I${pkgs.cppzmq}/include -I${pkgs.capnproto}/include -I${pkgs.eigen}/include/eigen3 -I${pkgs.libusb1.dev}/include -I${pkgs.openssl_3.dev}/include''${CPPFLAGS:+ $CPPFLAGS}"
            export LDFLAGS="-L${pkgs.zeromq}/lib -L${pkgs.capnproto}/lib -L${pkgs.libusb1}/lib -L${pkgs.openssl_3.out}/lib''${LDFLAGS:+ $LDFLAGS}"

            # Qt5 paths
            export QT_QPA_PLATFORM_PLUGIN_PATH="${pkgs.qt5.qtbase.bin}/lib/qt-${pkgs.qt5.qtbase.version}/plugins"
            export PATH="${pkgs.qt5.qtbase.dev}/bin:${pkgs.qt5.qttools.bin}/bin:$PATH"

            # capnproto path
            export PATH="${pkgs.capnproto}/bin:$PATH"

            echo "openpilot development shell activated"
            echo ""
            echo "Python: $(python --version)"
            echo "uv: $(uv --version)"
            echo ""
            echo "Next steps:"
            echo "  1. git submodule update --init --recursive"
            echo "  2. git lfs pull"
            echo "  3. scons -j$(nproc 2>/dev/null || sysctl -n hw.ncpu)"
          '';
        };
      }
    );

    # Also expose the Python package set for building
    packages = forAllSystems (system: {
      default = pythonSets.${system}.mkVirtualEnv "openpilot-env" workspace.deps.default;
    });
  };
}
