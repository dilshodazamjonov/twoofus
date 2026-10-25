// Typed wrappers for every backend endpoint the UI uses.
import { apiRequest } from "./client";
import type {
  AuthorizeOut,
  ConfigOut,
  DeviceFlowOut,
  DisconnectOut,
  InvitationCreatedOut,
  InvitationInspectOut,
  InvitationStatusOut,
  ProvidersOut,
  QuestionOut,
  RevokedOut,
  RoomNowPlayingOut,
  RoomOut,
  RoomRecentOut,
  SessionOut,
  SessionsOut,
  SetupStatusOut,
  SharingOut,
  SongsOut,
  TulipOut,
  TulipsOut,
  UserOut,
} from "./types";

type Signal = { signal?: AbortSignal };

export const api = {
  // ----- public -------------------------------------------------------------
  config: (o: Signal = {}) => apiRequest<ConfigOut>("/api/v1/config", o),
  session: (o: Signal = {}) => apiRequest<SessionOut>("/api/v1/auth/session", o),
  login: (username: string, password: string) =>
    apiRequest<SessionOut>("/api/v1/auth/login", { method: "POST", body: { username, password } }),
  logout: () => apiRequest<SessionOut>("/api/v1/auth/logout", { method: "POST" }),
  inspectInvitation: (token: string) =>
    apiRequest<InvitationInspectOut>("/api/v1/invitations/inspect", { method: "POST", body: { token } }),
  acceptInvitation: (body: { token: string; username: string; display_name: string; password: string }) =>
    apiRequest<SessionOut>("/api/v1/invitations/accept", { method: "POST", body }),

  // ----- me -----------------------------------------------------------------
  updateProfile: (display_name: string) =>
    apiRequest<UserOut>("/api/v1/me", { method: "PATCH", body: { display_name } }),
  deleteAccount: (password: string) =>
    apiRequest<void>("/api/v1/me", { method: "DELETE", body: { password } }),
  sharing: (o: Signal = {}) => apiRequest<SharingOut>("/api/v1/me/sharing", o),
  setSharing: (share_now_playing: boolean, acknowledged_notice_version: string | null) =>
    apiRequest<SharingOut>("/api/v1/me/sharing", {
      method: "PUT",
      body: { share_now_playing, acknowledged_notice_version },
    }),
  sessions: (o: Signal = {}) => apiRequest<SessionsOut>("/api/v1/me/sessions", o),
  revokeOtherSessions: () => apiRequest<RevokedOut>("/api/v1/me/sessions/revoke-others", { method: "POST" }),
  revokeSession: (id: string) =>
    apiRequest<void>(`/api/v1/me/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }),

  // ----- room ---------------------------------------------------------------
  room: (o: Signal = {}) => apiRequest<RoomOut>("/api/v1/room", o),
  nowPlaying: (o: Signal = {}) => apiRequest<RoomNowPlayingOut>("/api/v1/room/now-playing", o),
  tulips: (o: Signal = {}) => apiRequest<TulipsOut>("/api/v1/room/tulips", o),
  sendTulip: () => apiRequest<TulipOut>("/api/v1/room/tulips", { method: "POST" }),
  markTulipsSeen: () => apiRequest<TulipsOut>("/api/v1/room/tulips/seen", { method: "POST" }),
  recent: (o: Signal = {}) => apiRequest<RoomRecentOut>("/api/v1/room/recent", o),
  songs: (o: Signal = {}) => apiRequest<SongsOut>("/api/v1/room/songs", o),
  pickSong: (key: string) => apiRequest<SongsOut>("/api/v1/room/songs/pick", { method: "PUT", body: { key } }),
  unpickSong: () => apiRequest<SongsOut>("/api/v1/room/songs/pick", { method: "DELETE" }),
  addToPlaylist: (key: string) => apiRequest<SongsOut>("/api/v1/room/songs/playlist", { method: "POST", body: { key } }),
  removeFromPlaylist: (id: string) =>
    apiRequest<SongsOut>(`/api/v1/room/songs/playlist/${encodeURIComponent(id)}`, { method: "DELETE" }),
  question: (o: Signal = {}) => apiRequest<QuestionOut>("/api/v1/room/question", o),
  answerQuestion: (answer: string) => apiRequest<QuestionOut>("/api/v1/room/question", { method: "PUT", body: { answer } }),
  createInvitation: () => apiRequest<InvitationCreatedOut>("/api/v1/invitations", { method: "POST" }),
  currentInvitation: (o: Signal = {}) => apiRequest<InvitationStatusOut>("/api/v1/invitations/current", o),
  revokeInvitation: () => apiRequest<void>("/api/v1/invitations/current", { method: "DELETE" }),

  // ----- providers ----------------------------------------------------------
  providers: (o: Signal = {}) => apiRequest<ProvidersOut>("/api/v1/providers", o),
  disconnect: () => apiRequest<DisconnectOut>("/api/v1/providers/connection", { method: "DELETE" }),
  spotifyAuthorize: () => apiRequest<AuthorizeOut>("/api/v1/providers/spotify/authorize", { method: "POST" }),
  yandexStart: () => apiRequest<DeviceFlowOut>("/api/v1/providers/yandex/device-authorization", { method: "POST" }),
  yandexPoll: (o: Signal = {}) =>
    apiRequest<DeviceFlowOut>("/api/v1/providers/yandex/device-authorization/poll", { method: "POST", ...o }),
  yandexCancel: () => apiRequest<void>("/api/v1/providers/yandex/device-authorization", { method: "DELETE" }),
  setupStatus: (o: Signal = {}) => apiRequest<SetupStatusOut>("/api/v1/setup/status", o),
};
