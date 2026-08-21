# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

ARG BASE_IMAGE=python:3.12.11-slim-trixie@sha256:0b29ab9e420820f53d1cd5ce0157dfe07bea8a7cff5b4754d6d95c07b0e5bc47

FROM --platform=linux/amd64 ${BASE_IMAGE} AS ebook-tools-builder

ARG DEBIAN_SNAPSHOT=20260807T000000Z

COPY packaging/ebook-tools/toolchain.lock.json /toolchain/toolchain.lock.json
COPY packaging/ebook-tools/prepare_ebook_toolchain.py /toolchain/prepare_ebook_toolchain.py

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/%s trixie main\n' "${DEBIAN_SNAPSHOT}" > /etc/apt/sources.list \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        cmake \
        g++ \
        libfontconfig1-dev \
        libfreetype-dev \
        ninja-build \
        pkg-config \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python /toolchain/prepare_ebook_toolchain.py \
        --lock /toolchain/toolchain.lock.json \
        --cache /toolchain/downloads \
        --output /toolchain/prepared

RUN cmake -S /toolchain/prepared/poppler -B /toolchain/poppler-build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/poppler \
        -DBUILD_CPP_TESTS=OFF \
        -DBUILD_GTK_TESTS=OFF \
        -DBUILD_MANUAL_TESTS=OFF \
        -DBUILD_QT5_TESTS=OFF \
        -DBUILD_QT6_TESTS=OFF \
        -DENABLE_BOOST=OFF \
        -DENABLE_CPP=OFF \
        -DENABLE_GLIB=OFF \
        -DENABLE_GOBJECT_INTROSPECTION=OFF \
        -DENABLE_GPGME=OFF \
        -DENABLE_LCMS=OFF \
        -DENABLE_LIBCURL=OFF \
        -DENABLE_LIBJPEG=OFF \
        -DENABLE_LIBOPENJPEG=OFF \
        -DENABLE_LIBTIFF=OFF \
        -DENABLE_NSS3=OFF \
        -DENABLE_QT5=OFF \
        -DENABLE_QT6=OFF \
        -DENABLE_UNSTABLE_API_ABI_HEADERS=OFF \
        -DENABLE_UTILS=ON \
    && cmake --build /toolchain/poppler-build --target pdfinfo pdftotext \
    && install -d /opt/poppler/bin /opt/poppler/lib \
    && install -m 0755 \
        /toolchain/poppler-build/utils/pdfinfo \
        /toolchain/poppler-build/utils/pdftotext \
        /opt/poppler/bin/ \
    && cp -a /toolchain/poppler-build/libpoppler.so* /opt/poppler/lib/


FROM --platform=linux/amd64 ${BASE_IMAGE}

ARG DEBIAN_SNAPSHOT=20260807T000000Z

LABEL org.opencontainers.image.source="https://github.com/gecompat/FolioTone" \
      org.opencontainers.image.title="FolioTone E-book Toolchain" \
      org.opencontainers.image.description="Explicitly provisioned calibre, Poppler, Java, and EPUBCheck runtime"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FOLIOTONE_EBOOK_TOOLCHAIN_PROFILE=ebook-toolchain-linux-amd64/v1 \
    FOLIOTONE_EPUBCHECK_JAR=/opt/epubcheck/epubcheck.jar \
    JAVA_HOME=/opt/temurin-jre \
    LD_LIBRARY_PATH=/opt/poppler/lib \
    PATH=/opt/calibre:/opt/poppler/bin:/opt/temurin-jre/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/%s trixie main\n' "${DEBIAN_SNAPSHOT}" > /etc/apt/sources.list \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        fontconfig \
        libfontconfig1 \
        libfreetype6 \
        libgl1 \
        libnss3 \
        libxcb-cursor0 \
        libxkbcommon-x11-0 \
        poppler-data \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ebook-tools-builder /toolchain/prepared/calibre/ /opt/calibre/
COPY --from=ebook-tools-builder /toolchain/prepared/temurin-jre/ /opt/temurin-jre/
COPY --from=ebook-tools-builder /toolchain/prepared/epubcheck/ /opt/epubcheck/
COPY --from=ebook-tools-builder /opt/poppler/ /opt/poppler/
COPY --from=ebook-tools-builder /toolchain/prepared/poppler/COPYING /usr/share/licenses/poppler/COPYING
COPY --from=ebook-tools-builder /toolchain/prepared/poppler/COPYING3 /usr/share/licenses/poppler/COPYING3
COPY packaging/ebook-tools/toolchain.lock.json /usr/share/foliotone/ebook-toolchain.lock.json
COPY packaging/ebook-tools/THIRD_PARTY_NOTICES.md /usr/share/foliotone/THIRD_PARTY_NOTICES.md

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir . \
    && foliotone ebook-tools-doctor

RUN mkdir -p /data /media/ebooks /media/music

VOLUME ["/data"]

ENTRYPOINT ["foliotone"]
CMD ["ebook-tools-doctor"]
