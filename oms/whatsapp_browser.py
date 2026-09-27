"""WhatsApp Web adapter using visible UI, with recipient and send verification."""
import re
from urllib.parse import urlencode


class LoginRequired(RuntimeError):
    pass


def normalized(text):
    # WhatsApp renders formatting markers and these emoji as styled elements.
    for char in '*•👋📦🚚\ufe0f':
        text = text.replace(char, '')
    return re.sub(r'\s+', ' ', text).strip()


class WhatsAppBrowser:
    def __init__(self, page):
        self.page = page
        self.before = set()

    def signed_in(self):
        return self.page.get_by_role('button', name='New chat', exact=True).is_visible()

    def verify_recipient(self, phone):
        self.page.get_by_test_id('conversation-info-header').click(timeout=10000)
        drawer = self.page.get_by_test_id('chat-info-drawer')
        drawer.get_by_test_id('contact-info-header').wait_for(timeout=10000)
        matched = False
        for _ in range(20):
            text = drawer.inner_text()
            numbers = [re.sub(r'\D', '', line) for line in text.splitlines()
                       if re.fullmatch(r'\+?[\d ()-]{10,22}', line.strip())]
            if phone in numbers:
                matched = True
                break
            self.page.wait_for_timeout(250)
        if not matched:
            raise RuntimeError('Contact phone does not match the order.')
        drawer.get_by_role('button', name='Close', exact=True).click()

    def compose(self):
        return self.page.get_by_test_id('conversation-compose-box-input')

    def prepare(self, phone, body):
        if not re.fullmatch(r'947\d{8}', phone):
            raise ValueError('Invalid mobile number.')
        if not self.signed_in():
            raise LoginRequired('Link WhatsApp in the worker browser.')
        self.page.goto('https://web.whatsapp.com/send?' + urlencode({'phone': phone, 'text': body}))
        self.compose().wait_for(timeout=60000)
        # WhatsApp may expose the composer before it applies the linked draft.
        for _ in range(40):
            if normalized(self.compose().inner_text()) == normalized(body):
                break
            self.page.wait_for_timeout(250)
        if normalized(self.compose().inner_text()) != normalized(body):
            raise RuntimeError('The WhatsApp draft differs from the queued message.')
        self.verify_recipient(phone)
        self.before = set(self.page.locator('#main [data-id]').evaluate_all(
            '(els) => els.map(e => e.getAttribute("data-id"))'))

    def send(self, phone, body):
        self.verify_recipient(phone)
        if normalized(self.compose().inner_text()) != normalized(body):
            raise RuntimeError('Draft changed before sending.')
        self.page.locator('#main footer').get_by_role('button', name='Send', exact=True).click(timeout=10000)
        # A new outgoing bubble with this exact body must acquire a sent tick.
        for _ in range(60):
            if self.acknowledged(body):
                return
            self.page.wait_for_timeout(500)
        raise RuntimeError('WhatsApp send acknowledgement was not observed.')

    def prepare_photo(self, phone, body, path):
        from pathlib import Path
        path=Path(path).resolve(strict=True)
        self.prepare(phone, body)
        self.photo_recipient=phone
        self.photo_header=self.page.get_by_test_id('conversation-info-header-chat-title').inner_text()
        self.page.get_by_role('button',name='Attach',exact=True).click()
        with self.page.expect_file_chooser() as chooser:
            self.page.get_by_role('menuitem',name='Photos & videos',exact=True).click()
        chooser.value.set_files(str(path))
        caption=self.page.get_by_test_id('media-caption-input-container')
        caption.wait_for(timeout=15000)
        self.page.get_by_test_id('media-editor-canvas').wait_for(timeout=15000)
        self.page.get_by_role('button',name='Send 1 selected',exact=True).wait_for(timeout=15000)
        if normalized(caption.inner_text())!=normalized(body):
            raise RuntimeError('Photo caption differs from the requested message.')

    def send_photo(self, phone, body):
        if phone!=self.photo_recipient:
            raise RuntimeError('Photo recipient changed.')
        if self.page.get_by_test_id('conversation-info-header-chat-title').inner_text()!=self.photo_header:
            raise RuntimeError('Chat changed before photo send.')
        if normalized(self.page.get_by_test_id('media-caption-input-container').inner_text())!=normalized(body):
            raise RuntimeError('Photo caption changed before sending.')
        self.page.get_by_role('button',name='Send 1 selected',exact=True).click(timeout=10000)
        for _ in range(90):
            if self.acknowledged(body, require_photo=True):
                return
            self.page.wait_for_timeout(500)
        raise RuntimeError('Photo send acknowledgement was not observed.')

    def acknowledged(self, body, require_photo=False):
        for bubble in self.page.locator('#main [data-id]').all():
            identity = bubble.get_attribute('data-id')
            if not identity or identity in self.before:
                continue
            if require_photo and not bubble.get_by_test_id('image-thumb').count():
                continue
            texts = bubble.locator('[data-testid="selectable-text"], [data-testid="image-caption selectable-text"]').all_inner_texts()
            if not any(normalized(t) == normalized(body) for t in texts):
                continue
            statuses = bubble.get_by_test_id('msg-meta').locator('[aria-label]').evaluate_all(
                '(els) => els.map(e => e.getAttribute("aria-label").trim().toLowerCase())')
            if any(status in ('sent', 'delivered', 'read') for status in statuses):
                return True
        return False
