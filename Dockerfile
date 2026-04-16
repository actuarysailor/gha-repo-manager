FROM python:3.12-slim-bookworm AS builder
WORKDIR /app

# install build requirements
RUN apt-get update && apt-get install -y --no-install-recommends binutils patchelf build-essential git && rm -rf /var/lib/apt/lists/*

# copy the app
COPY ./ /app

# install python build requirements
RUN pip install --no-warn-script-location --upgrade pip poetry pyinstaller --constraint=package-requirements.txt

# build the app
RUN poetry build
# Install the app
RUN pip install dist/gha_repo_manager*.whl

# pyinstaller package the app
# https://docs.python.org/3/using/cmdline.html#interface-options
# OO flag is for optimization (first O omit asserts and debug statements, second omits docstrings)
# F flag is for one file, hidden-import is for cffi
RUN python -OO -m PyInstaller -F repo_manager/main.py --name repo-manager --hidden-import _cffi_backend --hidden-import tabulate
RUN strip -s -R .comment -R .gnu.version --strip-unneeded dist/repo-manager
# will be copied over to the final container, pyinstaller needs a /tmp to exist
RUN mkdir /app/tmp


FROM cicirello/pyaction:latest

ENTRYPOINT ["/repo-manager"]

COPY --from=builder /app/dist/repo-manager /repo-manager
COPY --from=builder /app/tmp /tmp

RUN git --version
RUN git config --global user.name "Repo Manager Bot"
RUN git config --global user.email "repo-mgr@bots.noreply.github.com"
