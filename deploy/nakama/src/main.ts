// Nakama server module: account rules, the lobby match (lobby.ts) and the lobby RPCs.
// Every function handed to `initializer` must be a top-level function declaration.

function beforeAuthenticateEmail(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama,
                                 data: nkruntime.AuthenticateEmailRequest): nkruntime.AuthenticateEmailRequest | void {
  if (data.create && !/^[A-Za-z0-9_]{3,20}$/.test(data.username || "")) {
    throw new Error("Username must be 3-20 letters, digits or _.");
  }
  return data;
}

function fail(message: string): string { return JSON.stringify({ ok: false, error: message }); }

function parseLabel(label: string): any {
  try { return JSON.parse(label); } catch (e) { return null; }
}

function launcherMaps(ctx: nkruntime.Context, nk: nkruntime.Nakama): any[] {
  const res = nk.httpRequest(ctx.env["LAUNCHER_URL"] + "/v1/maps", "get",
                             { "X-Launcher-Key": ctx.env["LAUNCHER_KEY"] }, "", 5000);
  if (res.code !== 200) { throw new Error("map list unavailable"); }
  return JSON.parse(res.body).maps;
}

function rpcLobbyMaps(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama, payload: string): string {
  return JSON.stringify({ ok: true, maps: launcherMaps(ctx, nk) });
}

function rpcLobbyCreate(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama, payload: string): string {
  if (!ctx.userId) { return fail("Sign in first."); }
  let req: any = null;
  try { req = JSON.parse(payload || "{}"); } catch (e) { return fail("Bad request."); }
  const name = typeof req.name === "string" ? req.name.trim() : "";
  if (name.length < 1 || name.length > NAME_MAX) { return fail("Name must be 1-32 characters."); }
  const seats = Number(req.seats);
  if (!(seats >= SEATS_MIN && seats <= SEATS_MAX && Math.floor(seats) === seats)) { return fail("Players must be 2-4."); }
  const isPrivate = req.private === true;
  const password = typeof req.password === "string" ? req.password : "";
  if (isPrivate && (password.length < 1 || password.length > PASSWORD_MAX)) {
    return fail("A private game needs a password of 1-32 characters.");
  }
  let mapName = "";
  for (const m of launcherMaps(ctx, nk)) { if (m.id === Number(req.map)) { mapName = String(m.name); } }
  if (!mapName) { return fail("Unknown map."); }
  for (const m of nk.matchList(100, true, null, null, null, null)) {
    const l = parseLabel(m.label);
    if (l && l.host_id === ctx.userId && l.phase === "open" && l.seats_used > 0) {
      return fail("You already have an open game.");
    }
  }
  const matchId = nk.matchCreate(LOBBY_MODULE, {
    name: name, map: Number(req.map), mapName: mapName, seats: seats, isPrivate: isPrivate,
    password: isPrivate ? password : "", hostUserId: ctx.userId,
  });
  return JSON.stringify({ ok: true, match_id: matchId });
}

function rpcLobbyList(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama, payload: string): string {
  let search = "";
  try {
    const req = JSON.parse(payload || "{}");
    if (typeof req.search === "string") { search = req.search.trim().toLowerCase(); }
  } catch (e) { search = ""; }
  const lobbies: object[] = [];
  for (const m of nk.matchList(100, true, null, null, null, null)) {
    const l = parseLabel(m.label);
    if (!l || l.kind !== "lobby" || l.phase !== "open" || l.seats_used < 1) { continue; }
    if (search && String(l.name).toLowerCase().indexOf(search) < 0) { continue; }
    lobbies.push({ match_id: m.matchId, name: l.name, map_name: l.map_name, seats_used: l.seats_used,
                   seats_max: l.seats_max, private: l.private === 1, host: l.host });
  }
  return JSON.stringify({ ok: true, lobbies: lobbies });
}

function InitModule(ctx: nkruntime.Context, logger: nkruntime.Logger, nk: nkruntime.Nakama,
                    initializer: nkruntime.Initializer) {
  initializer.registerBeforeAuthenticateEmail(beforeAuthenticateEmail);
  initializer.registerMatch(LOBBY_MODULE, {
    matchInit: lobbyMatchInit, matchJoinAttempt: lobbyMatchJoinAttempt, matchJoin: lobbyMatchJoin,
    matchLeave: lobbyMatchLeave, matchLoop: lobbyMatchLoop, matchTerminate: lobbyMatchTerminate,
    matchSignal: lobbyMatchSignal,
  });
  initializer.registerRpc("lobby_maps", rpcLobbyMaps);
  initializer.registerRpc("lobby_create", rpcLobbyCreate);
  initializer.registerRpc("lobby_list", rpcLobbyList);
  logger.info("prch module loaded");
}
