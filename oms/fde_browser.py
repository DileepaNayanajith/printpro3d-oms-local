"""Selectors observed on FDE Existing CCP / CRE, 25 September 2026.

Only the CCP digits path has been inspected. No private APIs or guessed receipts.
"""
import re
from decimal import Decimal
from urllib.parse import urlsplit

PORTAL_URL = 'https://www.fdedomestic.com/client/ccp_parcel_add.php'


class FormMismatch(RuntimeError):
    pass


class SignInRequired(FormMismatch):
    pass


def field_values(job):
    return {
        '#pDesc': f"{job['quantity']} x {job['product']}",
        '#OrderID': job['reference'], '#amount': f"{Decimal(job['cod_cents']) / 100:.2f}",
        '#rName': job['name'], '#rContact1': job['phone'], '#rContact2': '',
        '#rAddress': job['address'], '#Rrcity': job['city'],
    }


class FDEBrowser:
    def __init__(self, page):
        self.page = page
        self.city_id = None
        page.set_default_timeout(12000)

    def check_origin(self):
        url = urlsplit(self.page.url)
        if url.netloc == 'www.fdedomestic.com' and url.path == '/client/signIn.php':
            raise SignInRequired('Sign in in the dedicated browser')
        if url.scheme != 'https' or url.netloc != 'www.fdedomestic.com' or url.path != '/client/ccp_parcel_add.php':
            raise FormMismatch('Expected logged-in CCP page')

    def signed_in(self):
        url = urlsplit(self.page.url)
        return (url.scheme == 'https' and url.netloc == 'www.fdedomestic.com'
                and url.path in ('/client/welcome.php','/client/index.php','/client/ccp_parcel_add.php')
                and self.page.get_by_role('link', name=re.compile('Parcel Management')).count() == 1)

    def form_identity(self, job):
        self.check_origin()
        self.page.get_by_text(re.compile(r'^Parcel Details\s*-\s*' + re.escape(job['assigned_waybill']) + r'\s*$')).wait_for(state='visible')
        if self.page.locator('#ccpSecFrm').count() != 1:
            raise FormMismatch('Expected exactly one CCP form')

    def prepare(self, job):
        self.page.goto(PORTAL_URL, wait_until='domcontentloaded')
        self.check_origin()
        self.page.locator('#waybillNoR').fill(job['assigned_waybill'])
        self.page.locator('#btnSubmit').click()  # Lookup, not booking submission.
        self.form_identity(job)
        # Refuse an already-populated parcel rather than overwrite an existing record.
        for selector in ('#OrderID','#rName','#rContact1','#rAddress'):
            if self.page.locator(selector).input_value().strip():
                raise FormMismatch('Existing populated parcel requires reconciliation')
        self.page.locator('#ccpSecFrm select[name="weight"]').select_option(label=f"{job['weight_kg']}kg")
        for selector, value in field_values(job).items():
            if selector != '#Rrcity':
                self.page.locator(selector).fill(value)
        self.page.locator('#exchange').set_checked(False)
        city = self.page.locator('#Rrcity')
        city.fill('')
        city.press_sequentially(job['city'], delay=50)
        # Select exact destination, never the first similar city.
        option = self.page.locator('ul.ui-autocomplete:visible .ui-menu-item-wrapper').filter(
            has_text=re.compile(r'^' + re.escape(job['city'].strip()) + r'$', re.IGNORECASE))
        option.wait_for(state='visible')
        if option.count() != 1:
            raise FormMismatch('City is missing or ambiguous')
        option.click()
        # Live portal inspection: exact autocomplete selection can leave this
        # hidden input blank. Preserve portal behavior; never inject a guessed ID.
        self.city_id = self.page.locator('#RselectCityId').input_value().strip()
        self.verify(job)

    def verify(self, job):
        self.form_identity(job)
        for selector, expected in field_values(job).items():
            actual = self.page.locator(selector).input_value()
            if selector == '#amount':
                matches = Decimal(actual) == Decimal(expected)
            elif selector == '#Rrcity':
                matches = actual.strip().casefold() == expected.strip().casefold()
            else:
                matches = actual == expected
            if not matches:
                raise FormMismatch('Prepared form no longer matches saved order')
        if self.page.locator('#ccpSecFrm select[name="weight"]').input_value() != str(job['weight_kg']):
            raise FormMismatch('Weight changed')
        if self.page.locator('#exchange').is_checked():
            raise FormMismatch('Exchange changed')
        selected = self.page.locator('#RselectCityId').input_value().strip()
        if self.city_id is None or selected != self.city_id:
            raise FormMismatch('Destination selection is not confirmed')

    def submit(self):
        # Caller has persisted submitting state and verified a per-order approval.
        self.check_origin()
        # Reject a stale receipt before clicking; accept only the observed FDE
        # success heading + message produced by this submission.
        receipt = self.page.get_by_text('Add Successfully!', exact=True)
        if receipt.is_visible():
            raise FormMismatch('Previous receipt still visible')
        self.page.locator('#addCpParcel').click(no_wait_after=True)
        receipt.wait_for(state='visible', timeout=30000)
        self.check_origin()
        self.page.get_by_role('heading', name='Success!', exact=True).wait_for(state='visible')
        return True
