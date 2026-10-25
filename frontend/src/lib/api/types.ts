// Friendly names for the generated OpenAPI types (src/lib/api/schema.ts).
// Never hand-write response shapes: regenerate with `npm run api:types`.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type SessionOut = Schemas["SessionOut"];
export type UserOut = Schemas["UserOut"];
export type ConfigOut = Schemas["ConfigOut"];
export type RoomOut = Schemas["RoomOut"];
export type MemberOut = Schemas["MemberOut"];
export type InvitationStatusOut = Schemas["InvitationStatusOut"];
export type InvitationCreatedOut = Schemas["InvitationCreatedOut"];
export type InvitationInspectOut = Schemas["InvitationInspectOut"];
export type RoomNowPlayingOut = Schemas["RoomNowPlayingOut"];
export type MemberNowPlayingOut = Schemas["MemberNowPlayingOut"];
export type PlaybackOut = Schemas["PlaybackOut"];
export type PlaybackStatus = PlaybackOut["status"];
export type ProviderName = NonNullable<PlaybackOut["source"]>;
export type ProvidersOut = Schemas["ProvidersOut"];
export type ProviderAvailabilityOut = Schemas["ProviderAvailabilityOut"];
export type ConnectionOut = Schemas["ConnectionOut"];
export type DeviceFlowOut = Schemas["DeviceFlowOut"];
export type AuthorizeOut = Schemas["AuthorizeOut"];
export type DisconnectOut = Schemas["DisconnectOut"];
export type SetupStatusOut = Schemas["SetupStatusOut"];
export type SharingOut = Schemas["SharingOut"];
export type TulipsOut = Schemas["TulipsOut"];
export type TulipOut = Schemas["TulipOut"];
export type RoomRecentOut = Schemas["RoomRecentOut"];
export type MemberRecentOut = Schemas["MemberRecentOut"];
export type RecentTrackOut = Schemas["RecentTrackOut"];
export type SongsOut = Schemas["SongsOut"];
export type SongOut = Schemas["SongOut"];
export type PlaylistEntryOut = Schemas["PlaylistEntryOut"];
export type QuestionOut = Schemas["QuestionOut"];
export type SessionsOut = Schemas["SessionsOut"];
export type SessionInfoOut = Schemas["SessionInfoOut"];
export type RevokedOut = Schemas["RevokedOut"];
export type DemoScenarioOut = Schemas["DemoScenarioOut"];
export type DemoScenario = DemoScenarioOut["scenario"];
