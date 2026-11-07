ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.21
FROM ${BUILD_FROM}

WORKDIR /opt/family_hub_ui
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# The service definition: the base image's s6-overlay starts it with the add-on's environment
# (SUPERVISOR_TOKEN is there only for services, not for a plain CMD). No CMD here.
COPY rootfs /
RUN chmod a+x /etc/services.d/family_hub/run /etc/services.d/family_hub/finish
