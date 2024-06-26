FROM python:3.12-slim-bullseye AS builder
WORKDIR /app

# install build requirements # https://git-scm.com/download/linux
RUN apt-get update && apt-get install -y binutils patchelf build-essential scons upx git

# copy the app
COPY ./ /app

# install python build requirements
RUN pip install --no-warn-script-location --upgrade virtualenv pip poetry pyinstaller staticx --constraint=package-requirements.txt

# build the app
RUN poetry build
# Install the app
RUN pip install dist/gha_repo_manager*.whl

# pyinstaller package the app
# https://docs.python.org/3/using/cmdline.html#interface-options
# OO flag is for optimization (first O omit asserts and debug statements, second omits docstrings)
# F flag is for one file, hidden-import is for cffi
RUN python -OO -m PyInstaller -F repo_manager/main.py --name repo-manager --hidden-import _cffi_backend --hidden-import tabulate
# static link the repo-manager binary
RUN cd ./dist && \
    staticx -l $(ldconfig -p| grep libgcc_s.so.1 | awk -F "=>" '{print $2}' | tr -d " ") --strip repo-manager repo-manager-static && \
    strip -s -R .comment -R .gnu.version --strip-unneeded repo-manager-static
# will be copied over to the scratch container, pyinstaller needs a /tmp to exist
RUN mkdir /app/tmp


FROM cicirello/pyaction:latest

ENTRYPOINT ["/repo-manager"]

COPY --from=builder /app/dist/repo-manager-static /repo-manager
COPY --from=builder /app/tmp /tmp

RUN git --version
RUN git config --global user.name "Repo Manager Bot"
RUN git config --global user.email "repo-mgr@bots.noreply.github.com"
