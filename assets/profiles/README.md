# Print colour profile

Run `uv run python scripts/fetch-print-profile.py` from the repository root
to download **PSO Coated v3 (FOGRA51)** from the European Color Initiative.
The downloaded ICC profile and its accompanying information PDF are ignored
by Git. Normal builds do not access the network.

Source: https://eci.org/lib/exe/pso-coated_v3.zip

ICC SHA-256: `c30ad2c01e8f93135ec7682c535e0a81bc2d177c301e196376c5f5838b5c8e86`

The profile's embedded copyright notice permits use and embedding, but
restricts standalone redistribution. We therefore download the original
archive during setup instead of bundling the profile in this repository.
The printer has not supplied a press-specific profile; this is our default
for coated paper. Set `pdf.icc_profile` to use another CMYK output profile.

The embedded notice reads:

> This profile is made available by ECI European Color Initiative (www.eci.org),
> with permission of Heidelberger Druckmaschinen AG (www.heidelberg.com), and
> may be used, embedded and exchanged without restriction. It may not be
> distributed, sold or altered without written permission of ECI European
> Color Initiative. Color Toolbox 17.0.0 - (c) Copyright 2015 Heidelberger
> Druckmaschinen AG. All Rights Reserved.
