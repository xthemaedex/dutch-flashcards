import { send } from "./_lib.js";

// No per-word images in the deployed build (see images/README.md). The client
// only renders <img> for lemmas returned here, so an empty list = no image tags.
export default async function handler(req, res) {
  send(res, [], { maxAge: 3600 });
}
