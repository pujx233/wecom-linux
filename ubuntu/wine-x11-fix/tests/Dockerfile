FROM wecom-wine-x11-native-sdk:11.20
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 gcc-mingw-w64-i686 xvfb xcompmgr openbox \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
