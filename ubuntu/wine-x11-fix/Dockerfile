FROM ubuntu:26.04@sha256:c098726dd9b9733f3e885f8de0ef375206a311b0a317eadc40d347b1115fb944
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential bison flex pkg-config ca-certificates python3 desktop-file-utils clang-21 \
    gcc-mingw-w64-x86-64 gcc-mingw-w64-i686 \
    g++-mingw-w64-x86-64 g++-mingw-w64-i686 \
    libdbus-1-dev libfontconfig1-dev libfreetype-dev libx11-dev libx11-xcb-dev libxext-dev \
    libxi-dev libxrandr-dev libxrender-dev libxcursor-dev libxcomposite-dev libxdamage-dev \
    libxinerama-dev libxfixes-dev libxkbcommon-dev libxkbregistry-dev \
    libgl-dev libegl-dev libvulkan1 \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends libudev-dev libvulkan-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
