import json
import os
import unittest
from unittest.mock import Mock, patch

import requests
from flask import Flask

from src.models.note import Note
from src.models.user import db
from src.routes.note import note_bp


class TranslationRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI='sqlite://',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)
        self.app.register_blueprint(note_bp, url_prefix='/api')
        with self.app.app_context():
            db.create_all()
        self.client = self.app.test_client()
        self.api_key_patch = patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key'})
        self.api_key_patch.start()

    def tearDown(self):
        self.api_key_patch.stop()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def translate(self, payload):
        return self.client.post('/api/notes/translate', json=payload)

    def test_rejects_missing_or_unsupported_input(self):
        self.assertEqual(self.client.post('/api/notes/translate').status_code, 400)
        self.assertEqual(self.translate({'title': '', 'content': '', 'language': 'fr'}).status_code, 400)
        self.assertEqual(self.translate({'title': 'Hi', 'content': '', 'language': 'de'}).status_code, 400)
        self.assertEqual(self.translate({'title': 'Hi', 'content': '', 'language': []}).status_code, 400)

    def test_requires_api_key(self):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}):
            response = self.translate({'title': 'Hello', 'content': 'World', 'language': 'fr'})
        self.assertEqual(response.status_code, 503)
        self.assertIn('OPENROUTER_API_KEY', response.json['error'])

    @patch('src.routes.note.requests.post')
    def test_returns_translated_title_and_content(self, post):
        translated = {'title': 'Bonjour', 'content': 'Le monde'}
        post.return_value = Mock(
            ok=True,
            json=lambda: {'choices': [{'message': {'content': json.dumps(translated)}}]},
        )

        response = self.translate({'title': 'Hello', 'content': 'World', 'language': 'fr'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {**translated, 'language': 'fr'})
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer test-key')
        self.assertEqual(post.call_args.kwargs['timeout'], 30)

    @patch('src.routes.note.requests.post')
    def test_translation_does_not_modify_saved_notes(self, post):
        post.return_value = Mock(
            ok=True,
            json=lambda: {'choices': [{'message': {'content': '{"title": "Bonjour", "content": "Le monde"}'}}]},
        )
        with self.app.app_context():
            note = Note(title='Hello', content='World')
            db.session.add(note)
            db.session.commit()
            note_id = note.id

        response = self.translate({'title': 'Hello', 'content': 'World', 'language': 'fr'})

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            saved_note = db.session.get(Note, note_id)
            self.assertEqual(saved_note.title, 'Hello')
            self.assertEqual(saved_note.content, 'World')

    @patch('src.routes.note.requests.post')
    def test_reports_provider_failure(self, post):
        post.return_value = Mock(
            ok=False,
            status_code=401,
            json=lambda: {'error': {'message': 'Invalid API key'}},
        )

        response = self.translate({'title': 'Hello', 'content': 'World', 'language': 'ja'})

        self.assertEqual(response.status_code, 502)
        self.assertIn('Invalid API key', response.json['error'])

    @patch('src.routes.note.requests.post', side_effect=requests.Timeout())
    def test_reports_connection_failure(self, _post):
        response = self.translate({'title': 'Hello', 'content': 'World', 'language': 'zh-CN'})

        self.assertEqual(response.status_code, 502)
        self.assertIn('Could not connect', response.json['error'])

    @patch('src.routes.note.requests.post')
    def test_rejects_malformed_model_output(self, post):
        post.return_value = Mock(
            ok=True,
            json=lambda: {'choices': [{'message': {'content': '{"title": "Bonjour"}'}}]},
        )

        response = self.translate({'title': 'Hello', 'content': 'World', 'language': 'fr'})

        self.assertEqual(response.status_code, 502)
        self.assertIn('invalid translation', response.json['error'])


if __name__ == '__main__':
    unittest.main()
