import json
import os
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request
from src.models.note import Note, db

note_bp = Blueprint('note', __name__)

TRANSLATION_LANGUAGES = {
    'zh-CN': 'Simplified Chinese',
    'ja': 'Japanese',
    'fr': 'French',
}
TRANSLATION_PROMPT_PATH = Path(__file__).resolve().parents[1] / 'prompts' / 'translation.txt'
OPENROUTER_URL = os.environ.get('OPENROUTER_URL', 'https://openrouter.ai/api/v1/chat/completions')
# Ensure the URL points to the chat completions endpoint
if not OPENROUTER_URL.rstrip('/').endswith('chat/completions'):
    OPENROUTER_URL = OPENROUTER_URL.rstrip('/') + '/chat/completions'
DEFAULT_TRANSLATION_MODEL = os.environ.get('DEFAULT_TRANSLATION_MODEL', 'deepseek/deepseek-v4-flash-0731')


@note_bp.route('/notes', methods=['GET'])
def get_notes():
    """Get all notes, ordered by most recently updated"""
    notes = Note.query.order_by(Note.updated_at.desc()).all()
    return jsonify([note.to_dict() for note in notes])


@note_bp.route('/notes/translate', methods=['POST'])
def translate_note():
    """Translate a note without modifying the saved note."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'A JSON request body is required'}), 400

    title = data.get('title')
    content = data.get('content')
    language = data.get('language')
    if not isinstance(title, str) or not isinstance(content, str):
        return jsonify({'error': 'Title and content must be strings'}), 400
    if not title.strip() and not content.strip():
        return jsonify({'error': 'Enter a title or note content to translate'}), 400
    if not isinstance(language, str) or language not in TRANSLATION_LANGUAGES:
        return jsonify({'error': 'Choose Simplified Chinese, Japanese, or French'}), 400

    api_key = os.environ.get('OPENROUTER_API_KEY', '').strip()
    if not api_key:
        return jsonify({'error': 'Translation is not configured. Set OPENROUTER_API_KEY in the project .env file.'}), 503

    try:
        prompt = TRANSLATION_PROMPT_PATH.read_text(encoding='utf-8')
    except OSError:
        return jsonify({'error': 'The translation prompt could not be loaded.'}), 500

    model = os.environ.get('OPENROUTER_MODEL', DEFAULT_TRANSLATION_MODEL).strip() or DEFAULT_TRANSLATION_MODEL
    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': prompt},
                    {
                        'role': 'user',
                        'content': json.dumps({
                            'target_language': TRANSLATION_LANGUAGES[language],
                            'title': title,
                            'content': content,
                        }, ensure_ascii=False),
                    },
                ],
                'response_format': {'type': 'json_object'},
            },
            timeout=30,
        )
    except requests.RequestException:
        return jsonify({'error': 'Could not connect to the translation service. Please try again.'}), 502

    try:
        provider_data = response.json()
    except ValueError:
        return jsonify({'error': 'The translation service returned an invalid response.'}), 502

    if not response.ok:
        provider_error = provider_data.get('error', {}) if isinstance(provider_data, dict) else {}
        detail = provider_error.get('message') if isinstance(provider_error, dict) else None
        message = f'Translation service error (HTTP {response.status_code}).'
        if isinstance(detail, str) and detail.strip():
            message = f'{message} {detail.strip()}'
        return jsonify({'error': message}), 502

    try:
        translated_message = provider_data['choices'][0]['message']['content']
        translated_note = json.loads(translated_message)
    except (KeyError, IndexError, TypeError, ValueError):
        return jsonify({'error': 'The translation service returned an invalid translation.'}), 502

    translated_title = translated_note.get('title') if isinstance(translated_note, dict) else None
    translated_content = translated_note.get('content') if isinstance(translated_note, dict) else None
    if not isinstance(translated_title, str) or not isinstance(translated_content, str):
        return jsonify({'error': 'The translation service returned an invalid translation.'}), 502

    return jsonify({
        'title': translated_title,
        'content': translated_content,
        'language': language,
    })


@note_bp.route('/notes', methods=['POST'])
def create_note():
    """Create a new note"""
    try:
        data = request.json
        if not data or 'title' not in data or 'content' not in data:
            return jsonify({'error': 'Title and content are required'}), 400
        
        note = Note(title=data['title'], content=data['content'])
        db.session.add(note)
        db.session.commit()
        return jsonify(note.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@note_bp.route('/notes/<int:note_id>', methods=['GET'])
def get_note(note_id):
    """Get a specific note by ID"""
    note = Note.query.get_or_404(note_id)
    return jsonify(note.to_dict())

@note_bp.route('/notes/<int:note_id>', methods=['PUT'])
def update_note(note_id):
    """Update a specific note"""
    try:
        note = Note.query.get_or_404(note_id)
        data = request.json
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        note.title = data.get('title', note.title)
        note.content = data.get('content', note.content)
        db.session.commit()
        return jsonify(note.to_dict())
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@note_bp.route('/notes/<int:note_id>', methods=['DELETE'])
def delete_note(note_id):
    """Delete a specific note"""
    try:
        note = Note.query.get_or_404(note_id)
        db.session.delete(note)
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@note_bp.route('/notes/search', methods=['GET'])
def search_notes():
    """Search notes by title or content"""
    query = request.args.get('q', '')
    if not query:
        return jsonify([])
    
    notes = Note.query.filter(
        (Note.title.contains(query)) | (Note.content.contains(query))
    ).order_by(Note.updated_at.desc()).all()
    
    return jsonify([note.to_dict() for note in notes])
