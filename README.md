# ReelStock Frontend

ReelStock is a demonstration of an AI‑generated stock video library and creation studio built with Django.  This repository contains a fully functional frontend prototype that you can run locally for a software engineering course presentation.  The backend logic (database models, authentication, generation pipeline and moderation actions) is intentionally omitted in this phase.

## Features

- **Home** – landing page with links to browse the library or start creating.
- **Library** – grid of sample assets with search, category filter and pagination.  Each asset links to a detail page showing metadata and a download button.
- **Asset Detail** – displays a large preview and metadata, links to the creator’s profile and shows other assets by the same creator.  Includes a report modal (UI only).
- **Creator Profile** – shows a creator’s avatar, bio and their published assets.
- **Create/Studio** – prompt input and optional image upload with live preview.  A generated output placeholder appears when you click the generate button along with an “Add to Library” button (UI only).
- **My Assets** – lists draft and published assets for the current user with action buttons to publish, unpublish or delete (no persistence).
- **Moderation Dashboard** – admin‑style table listing all assets and reports with action buttons (UI only).
- **Authentication Pages** – simple login and registration forms without real authentication.

## Project Structure

The Django project follows the standard layout described in the official Django tutorial【140022745920203†L131-L167】:

```
reelstock/            # Django project root
├── manage.py         # Management utility【140022745920203†L144-L167】
├── reelstock/        # Project package (settings, URLs, WSGI/ASGI)【140022745920203†L144-L167】
├── core/             # Home and authentication pages
├── libraryapp/       # Public asset browsing and details
├── studio/           # Creation page and user dashboard
├── moderation/       # Admin-style moderation dashboard
├── data/             # JSON files containing mock assets, creators and reports
├── templates/        # Global templates and per-app templates
└── static/           # Bootstrap, custom CSS/JS and placeholder images
```

Mock data lives in the `data/` directory.  Views load these JSON files to populate the UI rather than using a database.  Static assets are stored under `static/`; a grey placeholder image is used for all thumbnails and avatars.

## Setup and Running

1. **Create a virtual environment** (recommended):

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```

2. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

3. **Run the development server**:

   ```bash
   python manage.py runserver
   ```

4. Open your browser and navigate to `http://127.0.0.1:8000/` to explore the site.  Use the navigation bar to move between pages.

This prototype does not implement database models, authentication or file storage.  All forms and admin actions are non‑functional placeholders for future development.