import {
  OpenposeAnimal,
  OpenposeBody,
  OpenposeFace,
  OpenposeHand,
  OpenposeObject,
  OpenposeKeypoint2D,
} from '../../Openpose';
import {describe, it, expect} from 'vitest'

describe('OpenposeObject', () => {
  it.each([
    new OpenposeKeypoint2D(-1, 1, 1.0, 'rgb(0, 0, 0)', 'name'),
    new OpenposeKeypoint2D(1, 1, 0.0, 'rgb(0, 0, 0)', 'name'),
    new OpenposeKeypoint2D(1, -1, 1.0, 'rgb(0, 0, 0)', 'name'),
  ])('Should set invalid keypoints invisible', (invalid_keypoint: OpenposeKeypoint2D) => {
    const object = new OpenposeObject([invalid_keypoint], []);
    expect(object.keypoints[0].visible).toBeFalsy();
  });

  it.each([
    new OpenposeKeypoint2D(1, 1, 1.0, 'rgb(0, 0, 0)', 'name'),
    new OpenposeKeypoint2D(100, 1, 1.0, 'rgb(0, 0, 0)', 'name'),
    new OpenposeKeypoint2D(0, 1, 0.25, 'rgb(0, 0, 0)', 'left edge'),
    new OpenposeKeypoint2D(1, 0, 0.75, 'rgb(0, 0, 0)', 'top edge'),
  ])('Should set valid keypoints visible', (valid_keypoint: OpenposeKeypoint2D) => {
    const object = new OpenposeObject([valid_keypoint], []);
    expect(object.keypoints[0].visible).toBeTruthy();
  });

  it('preserves non-binary confidence for body, hand, face and animal points', () => {
    const body = new OpenposeBody(Array.from({ length: 18 }, () => [1, 1, 0.25]));
    const hand = new OpenposeHand(Array.from({ length: 21 }, () => [0, 1, 0.5]));
    const face = new OpenposeFace(Array.from({ length: 70 }, () => [1, 0, 0.75]));
    const animal = new OpenposeAnimal(Array.from({ length: 17 }, () => [1, 1, 0.4]));

    expect(body.keypoints[0].confidence).toBe(0.25);
    expect(hand.keypoints[0].confidence).toBe(0.5);
    expect(hand.keypoints[0].visible).toBe(true);
    expect(face.keypoints[0].confidence).toBe(0.75);
    expect(face.keypoints[0].visible).toBe(true);
    expect(animal.keypoints[0].confidence).toBe(0.4);
  });

  it('serializes the detector confidence instead of forcing visible points to one', () => {
    const object = new OpenposeObject([
      new OpenposeKeypoint2D(0, 12, 0.37, 'rgb(0, 0, 0)', 'edge point'),
    ], []);
    object.openposeCanvas = { left: 0, top: 0 } as never;

    expect(object.serialize()).toEqual([0, 12, 0.37]);
  });

  it('restores confidence when the user makes a missing point visible', () => {
    const point = new OpenposeKeypoint2D(-1, -1, 0, 'rgb(0, 0, 0)', 'missing point');
    new OpenposeObject([point], []);
    point.x = 4;
    point.y = 8;
    point._visible = true;

    expect(point.confidence).toBe(1);
    expect(point.visible).toBe(true);
  });

  it('truncates extra keypoints to the supported schema', () => {
    const body = OpenposeBody.create(Array.from({ length: 20 }, () => [1, 1, 1]));
    const hand = OpenposeHand.create(Array.from({ length: 23 }, () => [1, 1, 1]));
    const face = OpenposeFace.create(Array.from({ length: 72 }, () => [1, 1, 1]));
    const animal = OpenposeAnimal.create(Array.from({ length: 19 }, () => [1, 1, 1]));

    expect(body?.keypoints).toHaveLength(18);
    expect(hand?.keypoints).toHaveLength(21);
    expect(face?.keypoints).toHaveLength(70);
    expect(animal?.keypoints).toHaveLength(17);
  });
});
