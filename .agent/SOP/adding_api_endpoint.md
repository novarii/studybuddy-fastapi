# SOP: Adding or Updating API Endpoints

Follow this checklist whenever you introduce a new FastAPI endpoint or expand an existing one.

1. **Plan the Contract**
   - Decide the route path, HTTP verb, and payload schema.
   - Extend or create Pydantic models in `app/models.py`. Keep optional fields explicit.
2. **Update Business Logic**
   - Add helper methods to `VideoDownloader`, `LocalStorage`, or new modules rather than inflating route handlers.
   - Keep background operations (downloads, conversions, transcriptions) inside dedicated classes so routes stay thin.
3. **Wire Routes**
   - Define the endpoint inside `app/main.py`.
   - Inject required dependencies (e.g., `storage`, `downloader`) instead of recreating them inside handlers.
4. **Persistence & Filesystem**
   - If storing new metadata, extend `VideoMetadata` and ensure `LocalStorage.store_video` (or new helpers) populate it.
   - Update `data/videos.json` schema documentation in `.agent/System/project_architecture.md` when structure changes.
5. **Testing**
   - Add pytest coverage (once the suite exists) using FastAPI’s `TestClient`. Mock external services such as `PanoptoDownloader` or ElevenLabs to keep tests deterministic.
6. **Docs & Env**
   - Document new environment variables or behaviors in `README.md` and `.env.example`.
   - Reflect changes in `.agent` docs (System/SOP) and commit them alongside code.

## Related Docs
- `.agent/System/project_architecture.md`
- `.agent/Tasks/current_features.md`
- `.agent/README.md`
