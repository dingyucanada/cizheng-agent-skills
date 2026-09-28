// Both homepage links and shared workbench links preserve the chosen dossier.
export function entryCaseID(href, caseIDs) {
  const url = new URL(href);
  let hash = '';
  try { hash = decodeURIComponent(url.hash.slice(1)); } catch { /* Ignore a malformed bookmark. */ }
  const query = url.searchParams.get('case') || '';
  return [hash, query].find(id => caseIDs.includes(id)) || null;
}

export function caseURL(href, id) {
  const url = new URL(href);
  url.searchParams.delete('case');
  url.hash = id;
  return url.pathname + url.search + url.hash;
}
