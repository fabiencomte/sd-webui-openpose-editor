import { describe, expect, it } from 'vitest';
import {
  getParentOrigin,
  isIncomingFrameMessage,
  isTrustedFrameEvent,
  parsePoseDataURL,
  readServerData,
} from '../../frameMessages';

const pose = {
  canvas_width: 512,
  canvas_height: 512,
  people: [],
  animals: [],
};

describe('frame message validation', () => {
  it('accepts only messages from the expected parent and origin', () => {
    const parent = {} as Window;
    const valid = {
      source: parent,
      origin: 'http://127.0.0.1:7862',
      data: { modalId: 'controlnet-0', poses: pose },
    } as MessageEvent;

    expect(isTrustedFrameEvent(valid, parent, valid.origin)).toBe(true);
    expect(isTrustedFrameEvent({ ...valid, source: {} } as MessageEvent, parent, valid.origin)).toBe(false);
    expect(isTrustedFrameEvent({ ...valid, origin: 'https://evil.example' } as MessageEvent, parent, valid.origin)).toBe(false);
  });

  it('rejects malformed payloads and non-image background URLs', () => {
    expect(isIncomingFrameMessage(null)).toBe(false);
    expect(isIncomingFrameMessage({ modalId: '', poses: pose })).toBe(false);
    expect(isIncomingFrameMessage({ modalId: 'x' })).toBe(false);
    expect(isIncomingFrameMessage({ modalId: 'x', imageURL: 'https://evil.example/a.png', poses: pose })).toBe(false);
    expect(isIncomingFrameMessage({ modalId: 'x', poses: { ...pose, canvas_width: 0 } })).toBe(false);
  });

  it('derives the parent origin without trusting an arbitrary message', () => {
    expect(getParentOrigin('http://127.0.0.1:7862/', 'http://127.0.0.1:9000')).toBe('http://127.0.0.1:7862');
    expect(getParentOrigin('', 'http://127.0.0.1:9000')).toBe('http://127.0.0.1:9000');
    expect(getParentOrigin('not a url', 'http://127.0.0.1:9000')).toBeNull();
  });

  it('decodes and validates pose data URLs', () => {
    const url = `data:application/json;base64,${btoa(JSON.stringify(pose))}`;
    expect(parsePoseDataURL(url)).toEqual(pose);
    expect(() => parsePoseDataURL('data:text/plain;base64,e30=')).toThrow();
    expect(() => parsePoseDataURL('data:application/json;base64,e30=')).toThrow('invalid structure');
  });
});

describe('server data transport', () => {
  it('reads JSON from a non-executable application/json element', () => {
    document.body.innerHTML = '<script id="openpose-server-data" type="application/json"></script>';
    document.getElementById('openpose-server-data')!.textContent = JSON.stringify({
      image_url: 'data:image/png;base64,abc',
      pose: '{"people":[]}',
    });
    expect(readServerData(document)?.image_url).toContain('image/png');
  });
});
