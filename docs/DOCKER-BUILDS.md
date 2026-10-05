# GitHub Docker builds

The [Docker images workflow](https://github.com/smallblocks/Offence/actions/workflows/docker.yml)
builds the repository Dockerfile on native Linux AMD64 and ARM64 runners. Relevant
pushes and pull requests trigger builds; maintainers can also use **Run workflow**.
Each image must start as UID/GID 10001 with a read-only root filesystem, dropped
capabilities, no network access and a passing local health check before upload.
The startup check does not exercise GPU inference or live payments.

## Download and load

Open a successful workflow run and download the artifact matching your Linux host:
`offence-linux-amd64` for x86-64, or `offence-linux-arm64` for ARM64.
GitHub requires sign-in to download Actions artifacts. Artifacts expire after
30 days; rerun the workflow to generate another build.

Extract the artifact ZIP. It contains a compressed Docker image, `SHA256SUMS`,
and `BUILD.txt` with the source commit, image tag and load command.
For example, on an AMD64 Linux host:

```sh
sha256sum -c SHA256SUMS
docker load -i offence-linux-amd64.tar.gz
```

Use the exact image tag from `BUILD.txt` when running the container. Retain the
restrictions in [compose.yaml](../compose.yaml): non-root user, read-only root,
dropped capabilities, no-new-privileges, process/memory/CPU limits, and a private
persistent data volume. Keep the API bound to loopback unless deliberately
configuring authenticated remote access. Set the Compose service's `image` to
the loaded tag and use `docker compose up --no-build -d` to avoid rebuilding.

The checksum detects download corruption. It is not an independent signature.
These are Docker image archives, not StartOS packages or a container-registry
publication. StartOS packages use the separate s9pk release process.
