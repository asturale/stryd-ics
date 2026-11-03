// Serve the feed only on your own domain (Pages environment variable FEED_HOST).
// *.pages.dev and per-deployment preview URLs get a 404, so old deploy URLs never
// expose the feed. No FEED_HOST set: everything is a 404 (closed by default).
export async function onRequest({ request, next, env }) {
  if (!env.FEED_HOST || new URL(request.url).hostname !== env.FEED_HOST) {
    return new Response("Not found\n", { status: 404 });
  }
  return next();
}
