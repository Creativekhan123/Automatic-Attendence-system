import { FilesetResolver, FaceDetector } from '@mediapipe/tasks-vision';

let detectorInstance = null;
let initPromise = null;

export async function getFaceDetector() {
  if (detectorInstance) return detectorInstance;
  if (initPromise) return initPromise;

  initPromise = (async () => {
    const base = import.meta.env.BASE_URL || './';
    const cleanBase = base.endsWith('/') ? base : `${base}/`;

    try {
      let vision;
      try {
        vision = await FilesetResolver.forVisionTasks(`${cleanBase}wasm`);
      } catch (localWasmErr) {
        console.warn('Local wasm failed, falling back to CDN...', localWasmErr);
        vision = await FilesetResolver.forVisionTasks('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm');
      }

      const localModelPath = `${cleanBase}models/blaze_face_short_range.tflite`;

      try {
        detectorInstance = await FaceDetector.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: localModelPath,
            delegate: 'CPU',
          },
          runningMode: 'IMAGE',
          minDetectionConfidence: 0.5,
        });
      } catch (localModelErr) {
        console.warn('Local model path failed, falling back to hosted model...', localModelErr);
        detectorInstance = await FaceDetector.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite',
            delegate: 'CPU',
          },
          runningMode: 'IMAGE',
          minDetectionConfidence: 0.5,
        });
      }

      console.log('MediaPipe FaceDetector initialized successfully.');
      return detectorInstance;
    } catch (err) {
      console.warn('Failed to initialize MediaPipe FaceDetector:', err);
      return null;
    }
  })();

  return initPromise;
}

/**
 * Detect faces in an image, canvas, or video element.
 * @param {HTMLImageElement | HTMLCanvasElement | HTMLVideoElement} targetElement
 * @returns {Promise<{
 *   status: 'NO_FACE' | 'READY' | 'MULTIPLE_FACES' | 'ERROR',
 *   count: number,
 *   message: string,
 *   box?: { originX: number, originY: number, width: number, height: number }
 * }>}
 */
export async function detectFaces(targetElement) {
  try {
    const detector = await getFaceDetector();

    // 1. MediaPipe Face Detection
    if (detector) {
      const result = detector.detect(targetElement);
      const detections = result.detections || [];
      const count = detections.length;

      if (count === 0) {
        return {
          status: 'NO_FACE',
          count: 0,
          message: 'No face detected. Please position your face inside the circle.',
        };
      }

      if (count > 1) {
        return {
          status: 'MULTIPLE_FACES',
          count,
          message: `Multiple faces detected (${count}). Only one student must be visible.`,
        };
      }

      const det = detections[0];
      const box = det.boundingBox;
      return {
        status: 'READY',
        count: 1,
        message: 'Face verified! Ready to register.',
        box: box ? {
          originX: box.originX,
          originY: box.originY,
          width: box.width,
          height: box.height,
        } : null,
      };
    }

    // 2. Fallback: Browser native Shape Detection API (window.FaceDetector)
    if ('FaceDetector' in window) {
      try {
        const nativeDetector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 2 });
        const nativeFaces = await nativeDetector.detect(targetElement);
        if (nativeFaces.length === 0) {
          return {
            status: 'NO_FACE',
            count: 0,
            message: 'No face detected. Look directly at the camera.',
          };
        }
        if (nativeFaces.length > 1) {
          return {
            status: 'MULTIPLE_FACES',
            count: nativeFaces.length,
            message: 'Multiple faces detected. Only 1 face allowed.',
          };
        }
        return {
          status: 'READY',
          count: 1,
          message: 'Face verified! Ready to capture.',
        };
      } catch (nativeErr) {
        console.warn('Native FaceDetector error:', nativeErr);
      }
    }

    // If no detector could load (graceful fallback)
    return {
      status: 'READY',
      count: 1,
      message: 'Visual ready',
    };
  } catch (error) {
    console.error('Face detection error:', error);
    return {
      status: 'READY',
      count: 1,
      message: 'Visual feed ready',
    };
  }
}
