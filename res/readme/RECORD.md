# Demo recording

```powershell
# Install PowerShell version of asciinema
dotnet tool install --global PowerSession

# Record session
powersession rec demo.cast

# Playback session
powersession play demo.cast

# Get conversion tools
pip install showreel
winget install Gyan.FFmpeg

# Generate intermediate mp4
showreel video demo.cast -o temp.mp4 --theme dracula --font "C:\Windows\Fonts\CascadiaMono.ttf"

# Convert to avif (do NOT put -r before -i, that forces a constant input FPS and collapses pause frames).
ffmpeg -fflags +genpts -i temp.mp4 -c:v libsvtav1 -crf 38 -preset 3 -pix_fmt yuv420p10le -svtav1-params "scm=1:tune=0:keyint=300" -loop 0 demo.avif
```
