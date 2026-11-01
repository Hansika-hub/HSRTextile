# Same image is used for staging and production (build once, deploy the same thing).
# Build context is the repository root (the folder that contains textile_inventory/).
FROM odoo:19.0

USER root
COPY textile_inventory /mnt/extra-addons/textile_inventory
RUN chown -R odoo:odoo /mnt/extra-addons
USER odoo
