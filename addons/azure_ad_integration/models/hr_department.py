import requests
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HRDepartment(models.Model):
    _inherit = 'hr.department'

    azure_dl_email = fields.Char("DL Email", readonly=True)
    azure_dl_id = fields.Char("DL ID", readonly=True)
    auto_sync_dl = fields.Boolean("Auto-Sync DL", default=True,
                                   help="Automatically find and link DL based on department name")

    def action_sync_dl_from_azure(self):
        """Find and link existing DL from Azure based on department name"""
        params = self.env['ir.config_parameter'].sudo()
        tenant = params.get_param("azure_tenant_id")
        client = params.get_param("azure_client_id")
        secret = params.get_param("azure_client_secret")
        domain = params.get_param("azure_domain")

        if not all([tenant, client, secret, domain]):
            _logger.error("❌ Azure credentials missing")
            return

        try:
            # Get token
            token_resp = requests.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client,
                    "client_secret": secret,
                    "scope": "https://graph.microsoft.com/.default"
                },
                timeout=30
            ).json()

            token = token_resp.get("access_token")
            if not token:
                _logger.error("❌ Failed to get token")
                return

            headers = {"Authorization": f"Bearer {token}"}

            # Generate expected DL email: Sales → DL_Sales@domain
            dept_name_clean = self.name.replace(' ', '_').replace('&', 'and')
            expected_dl_email = f"DL_{dept_name_clean}@{domain}"

            _logger.info(f"🔍 Searching for: {expected_dl_email}")

            # Search for group by email
            search_url = f"https://graph.microsoft.com/v1.0/groups?$filter=mail eq '{expected_dl_email}'"
            response = requests.get(search_url, headers=headers, timeout=30)

            if response.status_code == 200:
                groups = response.json().get('value', [])
                if groups:
                    group = groups[0]
                    self.write({
                        'azure_dl_email': group.get('mail'),
                        'azure_dl_id': group.get('id')
                    })
                    _logger.info(f"✅ Linked: {self.name} → {group.get('mail')}")
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'message': f"Linked to {group.get('mail')}",
                            'type': 'success',
                        }
                    }
                else:
                    _logger.warning(f"⚠️ DL not found: {expected_dl_email}")
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'message': f"DL not found: {expected_dl_email}. Please create it in Azure first.",
                            'type': 'warning',
                        }
                    }

        except Exception as e:
            _logger.error(f"❌ Error: {e}")

    @api.model
    def create(self, vals):
        """Auto-sync DL when department is created"""
        dept = super(HRDepartment, self).create(vals)
        if dept.auto_sync_dl:
            dept.action_sync_dl_from_azure()
        return dept