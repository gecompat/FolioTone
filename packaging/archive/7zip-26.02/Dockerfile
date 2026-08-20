FROM scratch
ADD rootfs.tar /
LABEL org.opencontainers.image.source="https://github.com/gecompat/FolioTone"
USER 65532:65532
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/7zzs"]
