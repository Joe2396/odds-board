import os

# Path to your odds_checker folder
folder = r"C:\epl-odds-model\src\app\data\auto\odds_checker"

# The script we want to insert
script = """
<script>
(function () {
  function sendHeight() {
    var h = Math.max(
      document.documentElement.scrollHeight,
      document.body.scrollHeight
    );
    // send height with a little padding
    window.parent.postMessage({ type: 'ODDS_IFRAME_HEIGHT', height: h + 20 }, '*');
  }
  window.addEventListener('load', function(){ setTimeout(sendHeight, 50); });
  window.addEventListener('resize', sendHeight);
  setInterval(sendHeight, 1000);
})();
</script>
"""

# Loop through all .html files in the folder
for filename in os.listdir(folder):
    if filename.endswith(".html"):
        path = os.path.join(folder, filename)

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # Only add script if not already present
        if "</body>" in content and "ODDS_IFRAME_HEIGHT" not in content:
            content = content.replace("</body>", script + "\n</body>")

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            print(f"✅ Updated {filename}")
        else:
            print(f"⏩ Skipped {filename} (already patched or no </body>)")
