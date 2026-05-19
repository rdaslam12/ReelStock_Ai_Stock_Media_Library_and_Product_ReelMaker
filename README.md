# ReelStock – Product CGI Reel Generator

ReelStock is an AI‑powered product media platform built with Django.  Users can upload a single product photo and let the system automatically remove the background, generate multiple cinematic scenes around the product and assemble a polished vertical reel with premium transitions.  The application also exposes a simple image generator based on HuggingFace’s text‑to‑image API and a lightweight community library where users can publish their generated assets.

This version of ReelStock includes a **fully working backend** for the product‑focused Reel Maker.  The classic static slideshow has been removed entirely; reels are now created via a CGI‑style pipeline that runs locally using Pillow and OpenCV.  The pipeline performs background removal, generates multiple scene plates (optionally using HuggingFace FLUX when a token is provided), composites your product into each scene with realistic lighting, adds Ken‑Burns‑style motion and rich transitions, and then renders the final vertical MP4.  Users can choose the approximate length of the final reel.

## Key Features

* **Home** – landing page with links to browse the library or start creating.
* **Library** – grid of sample assets with search, category filter and pagination.  Each asset links to a detail page showing metadata and a download button.
* **Asset Detail** – displays a large preview and metadata, links to the creator’s profile and shows other assets by the same creator.  Includes a report modal.
* **Creator Profile** – shows a creator’s avatar, bio and their published assets.
* **Reel Maker** – upload one product image, pick a product type, choose an approximate duration (4 s, 6 s or 8 s) and generate a cinematic reel locally.  The pipeline removes the background, generates five different environment backdrops, composites your product with shadows and reflections, applies motion and transitions, and renders a polished MP4.
* **Image Generator** – enter a text prompt and optional style to generate a single still image via the HuggingFace Inference API.
* **My Assets** – lists draft and published assets for the current user with actions to publish/unpublish.
* **Moderation Dashboard** – staff‑only table listing all assets and reports.
* **Authentication Pages** – registration and login flows powered by Django’s built‑in authentication system.

## Project Structure

The Django project follows a standard layout:

```
reelstock_v4/
├── manage.py            # Management utility
├── reelstock/           # Project package (settings, URLs, ASGI)
├── core/                # Home, auth and miscellaneous pages
├── libraryapp/          # Public asset browsing and details
├── studio/              # Creation tools: image generator and reel maker
├── moderation/          # Admin‑style moderation dashboard
├── templates/           # Global and per‑app templates
├── static/              # Bootstrap, custom CSS/JS and placeholder images
├── media/               # Uploaded and generated media files
└── data/                # JSON files containing mock assets and reports
```

Generated videos and intermediate frames are stored under the `media/` directory when running locally.  Django will serve these files automatically in DEBUG mode.

## Installation & Running

1. **Create a virtual environment** (recommended):

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```

2. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**:  Copy `.env.example` to `.env` and fill in any optional keys.  At minimum you should set `DJANGO_SECRET_KEY` to a random string.

   To unlock the AI features you must provide valid API credentials.  Without these tokens the system will still work, but scene generation will fall back to premium gradient backdrops.  Set these keys in your `.env` file **before** starting the server:

   * `HF_API_TOKEN` – your personal HuggingFace token used for background removal and optional scene generation.  Without this the pipeline uses local gradients.  You can obtain a token from your [HuggingFace tokens page](https://huggingface.co/settings/tokens).
   * `HF_IMAGE_MODEL` – (optional) override for the scene generator model.  Defaults to a FLUX.1‑style model.  Only used when `HF_API_TOKEN` is set.
   * `FAL_API_KEY` – (optional) API key for fal.ai image‑to‑video.  This integration is present in the codebase but is not used by the current reel pipeline.

4. **Apply database migrations** (first run only):

   ```bash
   python manage.py migrate
   ```

5. **Run the development server**:

   ```bash
   python manage.py runserver
   ```  

6. Open your browser and navigate to `http://127.0.0.1:8000/` to explore the site.  Log in or register to unlock the Reel Maker.

## Usage Tips

* Visit **Reel Maker** in the navigation bar.
* Choose a product type (e.g. Shoe, Watch, Bag or Other).  The shot plan preview on the left updates based on your selection.
* Upload a clear product photo (JPG, PNG or WebP up to 15 MB).
* Select a duration (4 s, 6 s or 8 s) to control how long the final reel should be.  This affects how long each shot is held in the final edit.
* Click **Generate Reel**.  The pipeline runs entirely locally, showing progress through background removal, scene generation, compositing and assembly.  Once complete you can preview the reel, download the MP4 and optionally publish it to the library.

> **Tip:** If you only see gradient backgrounds, double‑check that you have set a valid `HF_API_TOKEN` in your `.env` file and restarted the server.  Without a token the AI scene generator is disabled and a high‑quality gradient fallback is used instead.  The progress overlay will warn you when this happens.

## Notes

* Background removal prefers the `rembg` library if installed.  If not available or you do not set `HF_API_TOKEN`, an OpenCV GrabCut fallback is used.
* Scene generation uses HuggingFace FLUX when a token is provided.  Without a token, the system falls back to a premium radial gradient background with film grain and vignette for a polished look.
* Hold durations are distributed evenly across the number of frames.  The duration you choose is approximate; transitions and fade‑in/out add a small amount of extra time.
* No external video API calls are required for the main reel pipeline; everything runs locally using Pillow and OpenCV.  The fal.ai integration remains available in the codebase for future use but is not used by default.