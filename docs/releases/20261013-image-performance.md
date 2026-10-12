# Faster images ? 2026-10-13

Large originals were downloaded for feed and comment thumbnails. Precomputed WebP variants now supply suitable pixels; original download URLs and gallery zoom remain available. The default storage pipeline prepares variants for new uploads, and identical demo contents reuse encoding results. Clients accept older responses without variants.

Production backfill: 1,315 images ready, zero errors, originals backed up and retained. 960px inventory representation reduces transferred bytes by 90%; a repeated Slow 4G image benchmark reduces median loading from 9.57s to 1.32s. Flutter demo preview bytes are reduced by 90%.

Validation and publication are recorded in the workspace image performance audit. Web deployment still requires Vercel account authentication; do not treat a workflow with skipped deploy steps as publication.
