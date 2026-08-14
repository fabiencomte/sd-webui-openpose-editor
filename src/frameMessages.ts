import type { IOpenposeJson } from './Openpose';

export interface IncomingFrameMessage {
  modalId: string;
  imageURL?: string;
  poseURL?: string;
  poses?: IOpenposeJson | IOpenposeJson[];
}

export interface OutgoingFrameMessage {
  modalId: string;
  poseURL: string;
  poses: IOpenposeJson;
}

function isPose(value: unknown): value is IOpenposeJson {
  if (value === null || typeof value !== 'object') return false;
  const pose = value as Record<string, unknown>;
  return Number.isFinite(pose.canvas_width) && Number(pose.canvas_width) > 0
    && Number.isFinite(pose.canvas_height) && Number(pose.canvas_height) > 0
    && (pose.people === undefined || Array.isArray(pose.people))
    && (pose.animals === undefined || Array.isArray(pose.animals));
}

export function isIncomingFrameMessage(value: unknown): value is IncomingFrameMessage {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const message = value as Record<string, unknown>;
  if (typeof message.modalId !== 'string' || message.modalId.length === 0 || message.modalId.length > 256) {
    return false;
  }
  if (message.imageURL !== undefined
      && (typeof message.imageURL !== 'string' || !message.imageURL.startsWith('data:image/'))) {
    return false;
  }
  if (message.poseURL !== undefined
      && (typeof message.poseURL !== 'string'
        || !message.poseURL.startsWith('data:application/json;base64,'))) {
    return false;
  }
  if (message.poses !== undefined) {
    const poses = Array.isArray(message.poses) ? message.poses : [message.poses];
    if (poses.length === 0 || !poses.every(isPose)) return false;
  }
  return message.poseURL !== undefined || message.poses !== undefined;
}

export function getParentOrigin(referrer: string, ownOrigin: string): string | null {
  if (referrer) {
    try {
      const origin = new URL(referrer).origin;
      if (origin !== 'null') return origin;
    } catch {
      return null;
    }
  }
  return ownOrigin && ownOrigin !== 'null' ? ownOrigin : null;
}

export function isTrustedFrameEvent(
  event: MessageEvent,
  parentWindow: Window,
  parentOrigin: string | null,
): boolean {
  return parentOrigin !== null
    && event.source === parentWindow
    && event.origin === parentOrigin
    && isIncomingFrameMessage(event.data);
}

export function parsePoseDataURL(dataURL: string): IOpenposeJson {
  const prefix = 'data:application/json;base64,';
  if (!dataURL.startsWith(prefix)) throw new Error('Expected a base64 JSON data URL.');
  const encoded = dataURL.slice(prefix.length);
  if (encoded.length === 0 || encoded.length > 10_000_000) throw new Error('Pose data is empty or too large.');
  const parsed = JSON.parse(atob(encoded)) as unknown;
  if (!isPose(parsed)) throw new Error('Pose data has an invalid structure.');
  return parsed;
}

export function readServerData(document: Document): { image_url: string; pose: string } | null {
  const element = document.getElementById('openpose-server-data');
  if (element === null || element.textContent === null || element.textContent.trim() === '') return null;
  const value = JSON.parse(element.textContent) as unknown;
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
  const data = value as Record<string, unknown>;
  if (typeof data.image_url !== 'string' || typeof data.pose !== 'string') return null;
  return { image_url: data.image_url, pose: data.pose };
}

