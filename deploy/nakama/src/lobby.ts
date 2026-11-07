// Lobby match: one Nakama authoritative match per open game. Nakama owns the seats, ready
// flags, chat and host rules; when the host starts, it asks the launcher for a match server
// and hands every player their own ticket.
//
// The op codes and message shapes are a contract with the game client:
// Code/online/lobby_ops.py is the Python side. Change both together.

const LOBBY_MODULE = "lobby";
const LOBBY_TICK_RATE = 5;
const SEATS_MIN = 2;
const SEATS_MAX = 4;
const NAME_MAX = 32;
const PASSWORD_MAX = 32;
const CHARACTER_MAX = 64;
const CHAT_MAX_LEN = 200;
const CHAT_KEEP = 30;
const CHAT_MIN_TICKS = 2;
const PENDING_TICKS = LOBBY_TICK_RATE * 10;
const EMPTY_CLOSE_TICKS = LOBBY_TICK_RATE * 30;
const STARTED_CLOSE_TICKS = LOBBY_TICK_RATE * 15;
const LAUNCH_TIMEOUT_MS = 120000;

const OP_SET_CHARACTER = 1;
const OP_SET_READY = 2;
const OP_CHAT = 3;
const OP_START = 4;
const OP_STATE = 100;
const OP_TICKET = 101;
const OP_NOTICE = 102;

interface Seat { userId: string; username: string; sessionId: string; character: string; ready: boolean; lastChatTick: number; }
interface ChatLine { username: string; text: string; at: number; }
interface Pending { character: string; tick: number; }
interface LobbyState {
  name: string; map: number; mapName: string; seatsMax: number; isPrivate: boolean; password: string;
  hostUserId: string; phase: string; seats: Seat[];
  presences: {[sessionId: string]: nkruntime.Presence};
  pending: {[userId: string]: Pending};
  chat: ChatLine[]; emptyTicks: number; startedTick: number;
}

function findSeat(state: LobbyState, userId: string): number {
  for (let i = 0; i < state.seats.length; i++) { if (state.seats[i].userId === userId) { return i; } }
  return -1;
}

function findSeatBySession(state: LobbyState, sessionId: string): number {
  for (let i = 0; i < state.seats.length; i++) { if (state.seats[i].sessionId === sessionId) { return i; } }
  return -1;
}

function countKeys(obj: {[key: string]: any}): number {
  let n = 0;
  for (const k in obj) { if (obj.hasOwnProperty(k)) { n++; } }
  return n;
}

function cleanCharacter(value: any): string {
  if (typeof value !== "string") { return ""; }
  const c = value.trim();
  return c.length > 0 && c.length <= CHARACTER_MAX ? c : "";
}

function lobbyLabel(state: LobbyState): string {
  const i = findSeat(state, state.hostUserId);
  return JSON.stringify({
    kind: "lobby", name: state.name, map: state.map, map_name: state.mapName,
    seats_used: state.seats.length, seats_max: state.seatsMax, private: state.isPrivate ? 1 : 0,
    phase: state.phase, host: i >= 0 ? state.seats[i].username : "", host_id: state.hostUserId,
  });
}

function lobbyView(state: LobbyState): string {
  const seats: object[] = [];
  for (const s of state.seats) {
    seats.push({ user_id: s.userId, username: s.username, character: s.character, ready: s.ready,
                 host: s.userId === state.hostUserId });
  }
  return JSON.stringify({
    name: state.name, map: state.map, map_name: state.mapName, seats_max: state.seatsMax,
    private: state.isPrivate, phase: state.phase, host_user_id: state.hostUserId,
    seats: seats, chat: state.chat,
  });
}

function publish(dispatcher: nkruntime.MatchDispatcher, state: LobbyState): void {
  dispatcher.broadcastMessage(OP_STATE, lobbyView(state), null, null, true);
  dispatcher.matchLabelUpdate(lobbyLabel(state));
}

function notice(dispatcher: nkruntime.MatchDispatcher, text: string): void {
  dispatcher.broadcastMessage(OP_NOTICE, JSON.stringify({ text: text }), null, null, true);
}

function lobbyMatchInit(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama,
                        params: {[key: string]: any}) {
  const state: LobbyState = {
    name: String(params.name), map: Number(params.map), mapName: String(params.mapName),
    seatsMax: Number(params.seats), isPrivate: params.isPrivate === true,
    password: String(params.password || ""), hostUserId: String(params.hostUserId),
    phase: "open", seats: [], presences: {}, pending: {}, chat: [], emptyTicks: 0, startedTick: 0,
  };
  return { state: state, tickRate: LOBBY_TICK_RATE, label: lobbyLabel(state) };
}

function lobbyMatchJoinAttempt(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama,
                               dispatcher: nkruntime.MatchDispatcher, tick: number, state: LobbyState,
                               presence: nkruntime.Presence, metadata: {[key: string]: any}) {
  if (state.phase !== "open") {
    return { state: state, accept: false, rejectMessage: "This game has already started." };
  }
  const character = cleanCharacter(metadata.character);
  if (findSeat(state, presence.userId) >= 0) {
    state.pending[presence.userId] = { character: character, tick: tick };
    return { state: state, accept: true };
  }
  if (state.seats.length === 0 && presence.userId !== state.hostUserId) {
    return { state: state, accept: false, rejectMessage: "The host has not arrived yet." };
  }
  if (state.seats.length + countKeys(state.pending) >= state.seatsMax) {
    return { state: state, accept: false, rejectMessage: "This game is full." };
  }
  if (state.isPrivate && String(metadata.password || "") !== state.password) {
    return { state: state, accept: false, rejectMessage: "Wrong password." };
  }
  state.pending[presence.userId] = { character: character, tick: tick };
  return { state: state, accept: true };
}

function lobbyMatchJoin(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama,
                        dispatcher: nkruntime.MatchDispatcher, tick: number, state: LobbyState,
                        presences: nkruntime.Presence[]) {
  for (const p of presences) {
    const pend = state.pending[p.userId];
    delete state.pending[p.userId];
    const character = pend ? pend.character : "";
    const i = findSeat(state, p.userId);
    if (i >= 0) {
      delete state.presences[state.seats[i].sessionId];
      state.seats[i].sessionId = p.sessionId;
      if (character) { state.seats[i].character = character; }
    } else {
      state.seats.push({ userId: p.userId, username: p.username, sessionId: p.sessionId,
                         character: character, ready: false, lastChatTick: 0 });
    }
    state.presences[p.sessionId] = p;
  }
  publish(dispatcher, state);
  return { state: state };
}

function lobbyMatchLeave(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama,
                         dispatcher: nkruntime.MatchDispatcher, tick: number, state: LobbyState,
                         presences: nkruntime.Presence[]) {
  for (const p of presences) {
    delete state.presences[p.sessionId];
    const i = findSeatBySession(state, p.sessionId);
    if (i >= 0) { state.seats.splice(i, 1); }
  }
  if (state.seats.length > 0 && findSeat(state, state.hostUserId) < 0) {
    state.hostUserId = state.seats[0].userId;
  }
  if (state.phase === "open") { publish(dispatcher, state); }
  return { state: state };
}

function startMatch(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama,
                    dispatcher: nkruntime.MatchDispatcher, tick: number, state: LobbyState): void {
  if (state.phase !== "open") { return; }
  for (const s of state.seats) {
    if (!s.character) { notice(dispatcher, "Everyone must pick a character."); return; }
    if (s.userId !== state.hostUserId && !s.ready) { notice(dispatcher, "Everyone must be ready."); return; }
  }
  state.phase = "starting";
  publish(dispatcher, state);

  const players: object[] = [];
  for (const s of state.seats) {
    players.push({ user_id: s.userId, username: s.username, character: s.character });
  }
  let reply: any = null;
  let failure = "Could not start the game.";
  try {
    const res = nk.httpRequest(ctx.env["LAUNCHER_URL"] + "/v1/matches", "post",
      { "Content-Type": "application/json", "X-Launcher-Key": ctx.env["LAUNCHER_KEY"] },
      JSON.stringify({ match_id: ctx.matchId, map: state.map, players: players }), LAUNCH_TIMEOUT_MS);
    if (res.code === 200) {
      reply = JSON.parse(res.body);
    } else {
      logger.warn("launcher refused %s: %s", String(res.code), res.body);
      if (res.code === 503) { failure = "All game servers are busy. Try again soon."; }
    }
  } catch (e) {
    logger.error("launcher unreachable: %s", String(e));
  }
  if (!reply) {
    state.phase = "open";
    publish(dispatcher, state);
    notice(dispatcher, failure);
    return;
  }
  for (const s of state.seats) {
    const p = state.presences[s.sessionId];
    const ticket = reply.tickets[s.userId];
    if (p && ticket) {
      dispatcher.broadcastMessage(OP_TICKET,
        JSON.stringify({ host: reply.host, port: reply.port, map: reply.map, ticket: ticket }), [p], null, true);
    }
  }
  state.phase = "started";
  state.startedTick = tick;
  publish(dispatcher, state);
}

function lobbyMatchLoop(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama,
                        dispatcher: nkruntime.MatchDispatcher, tick: number, state: LobbyState,
                        messages: nkruntime.MatchMessage[]) {
  for (const uid in state.pending) {
    if (state.pending.hasOwnProperty(uid) && tick - state.pending[uid].tick > PENDING_TICKS) {
      delete state.pending[uid];
    }
  }
  if (state.seats.length === 0) {
    state.emptyTicks++;
    if (state.emptyTicks > EMPTY_CLOSE_TICKS) { return null; }
  } else {
    state.emptyTicks = 0;
  }
  if (state.phase === "started") {
    return tick - state.startedTick > STARTED_CLOSE_TICKS ? null : { state: state };
  }
  let changed = false;
  for (const m of messages) {
    const i = findSeatBySession(state, m.sender.sessionId);
    if (i < 0) { continue; }
    const seat = state.seats[i];
    let data: any = null;
    try { data = JSON.parse(nk.binaryToString(m.data)); } catch (e) { continue; }
    if (data === null || typeof data !== "object") { continue; }
    if (m.opCode === OP_SET_CHARACTER) {
      const c = cleanCharacter(data.character);
      if (c) { seat.character = c; seat.ready = false; changed = true; }
    } else if (m.opCode === OP_SET_READY) {
      seat.ready = data.ready === true;
      changed = true;
    } else if (m.opCode === OP_CHAT) {
      const text = typeof data.text === "string" ? data.text.trim() : "";
      if (text && text.length <= CHAT_MAX_LEN && tick - seat.lastChatTick >= CHAT_MIN_TICKS) {
        seat.lastChatTick = tick;
        state.chat.push({ username: seat.username, text: text, at: Date.now() });
        if (state.chat.length > CHAT_KEEP) { state.chat.splice(0, state.chat.length - CHAT_KEEP); }
        changed = true;
      }
    } else if (m.opCode === OP_START && seat.userId === state.hostUserId) {
      startMatch(ctx, logger, nk, dispatcher, tick, state);
    }
  }
  if (changed) { publish(dispatcher, state); }
  return { state: state };
}

function lobbyMatchTerminate(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama,
                             dispatcher: nkruntime.MatchDispatcher, tick: number, state: LobbyState,
                             graceSeconds: number) {
  notice(dispatcher, "The server is restarting.");
  return { state: state };
}

function lobbyMatchSignal(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama,
                          dispatcher: nkruntime.MatchDispatcher, tick: number, state: LobbyState,
                          data: string) {
  return { state: state, data: "" };
}
