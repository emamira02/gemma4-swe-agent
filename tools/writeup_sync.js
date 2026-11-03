// Sync the Kaggle Writeup draft with paper/PAPER.md at a given commit.
// Run in the writeup page in Edit mode (browser console or automation): await syncWriteup('<commit sha>')
// Keeps the Kaggle-hosted figure URLs already in the description (matched by "Figure N" alt text);
// a new figure must first be uploaded through the editor's "Insert Image" button.
// Title and subtitle are separate fields: set them from the first two lines of PAPER.md by hand.
async function syncWriteup(sha) {
  const ta = document.querySelector('textarea[aria-label="Project Description"]');
  if (!ta) throw new Error('open the writeup in Edit mode first');
  const urls = {};
  for (const m of ta.value.matchAll(/!\[(Figure \d+)\]\((https:\/\/www\.googleapis\.com\/[^)\s]+)\)/g)) urls[m[1]] = m[2];
  const r = await fetch(`https://raw.githubusercontent.com/emamira02/gemma4-swe-agent/${sha}/paper/PAPER.md`);
  if (!r.ok) throw new Error(`PAPER.md at ${sha}: HTTP ${r.status}`);
  const md = (await r.text()).replace(/\r\n/g, '\n');
  const start = md.indexOf('## Abstract');
  if (start < 0) throw new Error('no "## Abstract" heading');
  const missing = [];
  const body = md.slice(start).trim().replace(/!\[(Figure \d+)\]\(figures\/[^)]+\)/g,
    (m, alt) => urls[alt] ? `![${alt}](${urls[alt]})` : (missing.push(alt), m)) + '\n';
  if (missing.length) throw new Error('no Kaggle-hosted image for ' + missing.join(', '));
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(ta, body);
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  return { tokens: body.trim().split(/\s+/).length, figures: Object.keys(urls).length };
}
