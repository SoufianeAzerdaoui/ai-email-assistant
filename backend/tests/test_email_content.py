"""Unit tests for safe HTML email fallback conversion."""

import unittest

from app.email_content import html_to_readable_text, readable_email_body


class EmailContentTests(unittest.TestCase):
    def test_prefers_plain_text_and_normalizes_line_endings(self):
        result = readable_email_body(
            "  Bonjour\r\n\r\nVersion texte.  ",
            "<p>Version HTML ignorée.</p>",
        )
        self.assertEqual(result, "Bonjour\n\nVersion texte.")

    def test_converts_paragraphs_entities_lists_and_useful_links(self):
        html = """
        <!doctype html>
        <html><head><style>body { color: red }</style></head><body>
          <p>Bonjour&nbsp;Alice &amp; Bob,</p>
          <p>Votre dossier est prêt.<br>Merci.</p>
          <ul><li>Facture</li><li>Contrat</li></ul>
          <p><a href="https://example.test/dossier">Ouvrir le dossier</a></p>
          <script>alert('ignored')</script>
        </body></html>
        """
        self.assertEqual(
            html_to_readable_text(html),
            "Bonjour Alice & Bob,\n\nVotre dossier est prêt.\nMerci.\n\n"
            "• Facture\n• Contrat\n\nOuvrir le dossier (https://example.test/dossier)",
        )

    def test_ignores_active_and_unsafe_link_content(self):
        html = '<p>Message <a href="javascript:alert(1)">ici</a>.</p>'
        self.assertEqual(html_to_readable_text(html), "Message ici.")

    def test_removes_invisible_characters_and_limits_empty_lines(self):
        html = (
            "<h1>Confirmation\u200b</h1><p>\ufeff&nbsp;Bonjour&nbsp;Alice&nbsp;</p>"
            "<div>\u2060</div><div><br><br><br></div><p>Merci.</p>"
        )
        self.assertEqual(
            html_to_readable_text(html),
            "Confirmation\n\nBonjour Alice\n\nMerci.",
        )

    def test_hides_labeled_tracking_url_but_keeps_useful_links(self):
        tracking_url = "https://www.helloasso.com/click?redirect=" + ("x" * 180)
        html = (
            f'<p><a href="{tracking_url}">Voir mon inscription</a></p>'
            '<p><a href="https://example.test/billet">Télécharger le billet</a></p>'
        )
        self.assertEqual(
            html_to_readable_text(html),
            "Voir mon inscription\n\nTélécharger le billet (https://example.test/billet)",
        )

    def test_normalizes_plain_text_invisible_and_blank_lines(self):
        result = readable_email_body(
            "Titre\u200b\n\ufeff\n\n\n\u2060\nParagraphe",
            None,
        )
        self.assertEqual(result, "Titre\n\nParagraphe")


if __name__ == "__main__":
    unittest.main()
