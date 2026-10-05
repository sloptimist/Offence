"""Export the existing page's vector artwork as a social card (requires CairoSVG)."""
from pathlib import Path
import random
import re
import cairosvg

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / 'site/index.html').read_text()
logo = re.search(r'<svg class="wordmark".*?</svg>', html, re.S).group()
logo = re.sub(r'<svg[^>]*>', '<svg x="367" y="122" width="466" height="56" viewBox="0 0 59 7" color="#3b363c">', logo)
scene = re.search(r'<svg viewBox="0 0 480 250".*?</svg>', html, re.S).group()
scene = scene.replace('<svg viewBox=', '<svg x="365" y="196" width="470" height="245" viewBox=')
for old,new in {'#cbff70':'#c6cc91','#b9a0ed':'#a99aaa','#f5f1e5':'#d6ccb2','#211c29':'#39373c'}.items():
    scene = scene.replace(old,new)
rng=random.Random(31)
speckles=''.join(f'<rect x="{rng.uniform(309,890):.1f}" y="{rng.uniform(48,534):.1f}" width="{rng.choice([.6,1,1.5,2])}" height="1" fill="{rng.choice(["#eee7d6","#45463f"])}" opacity=".18"/>' for _ in range(1700))
grooves=''.join(f'<path d="M308 {y}h24M868 {y}h24" stroke="#77796f" stroke-width="3"/><path d="M308 {y+3}h24M868 {y+3}h24" stroke="#c0beb2" stroke-width="2"/>' for y in range(120,475,13))
contacts=''.join(f'<rect x="{x}" y="518" width="9" height="23" fill="#b5a164"/>' for x in range(508,696,16))
svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="600" viewBox="0 0 1200 600">
<defs><radialGradient id="bg"><stop stop-color="#70665a"/><stop offset="1" stop-color="#302f2b"/></radialGradient><linearGradient id="shell" x2=".9" y2="1"><stop stop-color="#bcb9ab"/><stop offset=".6" stop-color="#a5a396"/><stop offset="1" stop-color="#92958a"/></linearGradient><linearGradient id="label"><stop stop-color="#c0aeb5"/><stop offset="1" stop-color="#a192a3"/></linearGradient></defs>
<rect width="1200" height="600" fill="url(#bg)"/>
<g transform="rotate(-3 600 300)">
<rect x="303" y="52" width="608" height="510" rx="12" fill="#171815" opacity=".35"/>
<rect x="298" y="38" width="604" height="506" rx="12" fill="url(#shell)" stroke="#62655b" stroke-width="4"/>
<path d="M302 528V51q0-9 10-9h576" fill="none" stroke="#d3d0bf" stroke-width="3"/>
<path d="M899 51v479q0 10-10 10H311" fill="none" stroke="#787c6f" stroke-width="5"/>
{grooves}
<text x="346" y="71" font-family="monospace" font-size="10" letter-spacing="2" fill="#75786d">OFFENCE ENTERTAINMENT SYSTEM</text><path d="M842 59h12l-6 9z" fill="#797c70"/>
<rect x="344" y="85" width="512" height="399" rx="5" fill="url(#label)" stroke="#716b60" stroke-width="2"/>
<path d="M344 86h24l-24 24z" fill="#aaa89b"/><path d="M345 109l24-23-3 21z" fill="#d5c6b4"/>
<text x="367" y="108" font-family="monospace" font-size="8" letter-spacing="1" fill="#484049">PERMISSIONLESS AI INFERENCE</text><text x="834" y="108" text-anchor="end" font-family="monospace" font-size="8" fill="#484049">UNLIMITED PEERS</text>
{logo}
<rect x="365" y="187" width="470" height="260" fill="#39373c" stroke="#51484e" stroke-width="2"/>
{scene}
<text x="378" y="438" fill="#bfb69f" font-family="monospace" font-size="8" letter-spacing="1">PEER TO PEER / NO CENTRAL LOBBY</text>
<text x="367" y="468" fill="#484049" font-family="monospace" font-size="8" letter-spacing=".8">YOUR HARDWARE. YOUR MODEL. YOUR TERMS.</text><circle cx="818" cy="464" r="12" fill="none" stroke="#5b5256" stroke-width="2"/><text x="818" y="468" text-anchor="middle" font-family="monospace" font-size="11" fill="#5b5256">01</text>
<path d="M387 94l36 1m-66 380 32-1m429-118 3-41m-421-125 19 1m-65 339 41-1" stroke="#e4d8bf" stroke-width="1" opacity=".6"/>
{speckles}
<g fill="#8b8e7f" stroke="#62675c" stroke-width="2"><circle cx="325" cy="517" r="8"/><circle cx="875" cy="517" r="8"/></g><path d="M320 519l10-4m540 4 10-4" stroke="#53584d" stroke-width="2"/>
<path d="M496 544v-34h208v34" fill="#34372e" stroke="#797e6e" stroke-width="5"/>{contacts}
</g></svg>'''
# Keep editable vector source alongside the deployable image.
(ROOT / 'assets/offence-social.svg').write_text(svg)
cairosvg.svg2png(bytestring=svg.encode(),write_to=str(ROOT / 'site/offence-cartridge.png'))
print('Wrote 1200 x 600 social card.')
