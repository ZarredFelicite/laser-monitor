{
  description = "Laser Monitor Development Environment using YOLOE";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
          config.cudaSupport = false;
          config.allowUnsupportedSystem = true;
        };

        buildInputs = with pkgs; [
          # System libraries for computer vision and ML
          taglib
          openssl
          git
          libxml2
          libxslt
          libzip
          zlib
          stdenv.cc.cc.lib
          stdenv.cc
          ncurses5
          binutils
          gitRepo gnupg autoconf curl
          procps gnumake util-linux m4 gperf unzip
          libGLU libGL
          glib
          freeglut
          gcc
          # Additional libraries for OpenCV and ML
          libuv
          ffmpeg
          libgcc
          portaudio
          linuxHeaders
          xorg.libX11
          xorg.libXtst
          #libsForQt5.qt5.qtwayland
          qt6.qtbase
          xorg.libSM
          xorg.libICE
        ];

        devTools = with pkgs; [
          git
          bash
          uv
          neovim
        ];

        python = pkgs.python312.withPackages (ps: with ps; [
          # Minimal base packages - most will be managed by uv
        ]);

        laser-monitor = pkgs.writeScriptBin "laser-monitor" ''
          #!/usr/bin/env bash
          source .venv/bin/activate
          python cli.py monitor "$@"
        '';

        setup-yoloe = pkgs.writeScriptBin "setup-yoloe" ''
          #!/usr/bin/env bash
          source .venv/bin/activate
          python setup_yoloe.py "$@"
        '';

        libPath = pkgs.lib.makeLibraryPath buildInputs;

        env = {
          LD_LIBRARY_PATH = "${libPath}:/run/opengl-driver/lib:/run/opengl-driver-32/lib";
          QT_QPA_PLATFORM_PLUGIN_PATH = "${pkgs.qt6.qtbase}/lib/qt-6/plugins/platforms";
          QT_QPA_PLATFORM = "wayland;xcb";
        };

        exportEnv = pkgs.lib.concatStringsSep "\n" (
          map (n: "export ${n}=\"${env.${n}}\"") (builtins.attrNames env)
        );

      in {
        devShells.default = pkgs.mkShell {
          inherit buildInputs;
          packages = devTools ++ [ python laser-monitor setup-yoloe ];

          # Provide run-time libs automatically
          LD_LIBRARY_PATH = env.LD_LIBRARY_PATH;

          shellHook = ''
            ${exportEnv}

            echo "🔥 Laser Monitor Development Environment"
            echo "Using uv for Python package management"
            echo ""

            # Create lightweight local venv using uv
            if [ ! -d ".venv" ]; then
              echo "Creating local python venv (.venv) using uv..."
              uv venv --python ${python.interpreter}
            fi

            # Keep venv in-sync with pyproject.toml
            echo "Syncing dependencies with uv..."
            uv sync

            source .venv/bin/activate

            echo ""
            echo "Available commands:"
            echo "  laser-monitor  - Run the laser monitor"
            echo "  setup-yoloe    - Setup YOLOE visual prompts"
            echo ""
            echo "YOLOE models will be downloaded to ./pretrain/"
            echo "Make sure to create your visual prompts configuration!"
            echo ""
            echo "To get YOLOE models:"
            echo "  wget https://huggingface.co/jameslahm/yoloe/resolve/main/yoloe-v8s-seg.pt -P pretrain/"
            echo "  wget https://huggingface.co/jameslahm/yoloe/resolve/main/yoloe-v8l-seg.pt -P pretrain/"

            # Create directories if they don't exist
            mkdir -p pretrain
            mkdir -p logs
            mkdir -p images
            mkdir -p config
          '';
        };
      });
}
