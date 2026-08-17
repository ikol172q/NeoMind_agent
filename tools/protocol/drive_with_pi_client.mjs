// Drive NeoMind's pi server with pi's OWN client library.
//
// The point is that none of the client code here is ours: PiClient does the
// handshake, framing, request correlation and event dispatch. If our server
// disagrees with the protocol, this fails — the way a real client would.
import net from "node:net";
import { PiClient } from "./packages/client/src/index.ts";

const port = Number(process.argv[2] || 8791);
const log = (...a) => console.log(" ", ...a);

const transportFactory = async (handlers) => {
  const socket = net.createConnection({ host: "127.0.0.1", port });
  await new Promise((res, rej) => {
    socket.once("connect", res);
    socket.once("error", rej);
  });
  socket.on("data", (b) => handlers.onData(new Uint8Array(b)));
  socket.on("close", () => handlers.onClose());
  socket.on("error", (e) => handlers.onError(e));
  return {
    async send(chunk) {
      await new Promise((res, rej) =>
        socket.write(Buffer.from(chunk), (e) => (e ? rej(e) : res())),
      );
    },
    close() { socket.destroy(); },
  };
};

const client = new PiClient({ transportFactory });

const progress = [];
client.onEvent((e) => {
  if (e.type === "session_progress") progress.push(e.progress);
});

const snapshot = await client.connect();
log("connect       → serverId:", snapshot.serverId, "| protocol:", snapshot.protocolVersion);

const sessions0 = await client.listSessions();
log("listSessions  →", sessions0.length, "session(s)");

const handle = await client.createSession({ cwd: "/tmp", model: { provider: "neomind", id: "test" } });
log("createSession → id:", handle.id);

const after = await handle.prompt("hello from pi's own client");
log("prompt        → phase:", after.phase);

await new Promise((r) => setTimeout(r, 1200));
log("progress      →", progress.map((p) => p.type + (p.kind ? `(${p.kind})` : "")).join(", ") || "(none)");
const text = progress.filter((p) => p.type === "assistant_delta" && p.kind === "text")
                     .map((p) => p.delta).join("");
log("streamed text →", JSON.stringify(text));

try {
  await handle.steer("intervene");
  log("steer         → ✗ should have been refused");
} catch (e) {
  log("steer         → refused:", String(e.message || e).slice(0, 60));
}

const aborted = await handle.abort();
log("abort         → phase:", aborted.phase);

await handle.detach();
log("detach        → ok");
client.disconnect();
log("disconnect    → ok");
