import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Camera, Check, UserPlus, Image as ImageIcon, RotateCcw, Sparkles, ShieldAlert, CheckCircle2, Scan } from 'lucide-react';
import confetti from 'canvas-confetti';
import { detectFaces, getFaceDetector } from '../services/faceDetector';

export default function AddStudentView({ buses, students, onStudentCreated }) {
  // Suggest next ID
  const suggestNextId = () => {
    if (!students || students.length === 0) return '01';
    const nums = students
      .map((s) => parseInt(s.student_id, 10))
      .filter((n) => !isNaN(n));
    if (nums.length === 0) return String(students.length + 1).padStart(2, '0');
    const max = Math.max(...nums);
    return String(max + 1).padStart(2, '0');
  };

  const [studentId, setStudentId] = useState(suggestNextId());
  const [name, setName] = useState('');
  const [className, setClassName] = useState('5A');
  const [busId, setBusId] = useState(buses[0]?.bus_id || 'Bus01');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successToast, setSuccessToast] = useState(null);

  // Camera & Face Detection State
  const [isCameraActive, setIsCameraActive] = useState(false);
  const [capturedPhoto, setCapturedPhoto] = useState(null);
  const [photoVerified, setPhotoVerified] = useState(false);
  const [cameraError, setCameraError] = useState(null);

  // Real-time Face Validation State: 'NO_FACE' | 'READY' | 'MULTIPLE_FACES' | 'IDLE' | 'CHECKING'
  const [faceCheckStatus, setFaceCheckStatus] = useState('IDLE');
  const [faceCheckMessage, setFaceCheckMessage] = useState('Camera inactive');
  const [, setDetectedBox] = useState(null);

  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const fileInputRef = useRef(null);
  const checkIntervalRef = useRef(null);

  // Pre-load detector on mount for instant zero-delay face checks
  useEffect(() => {
    getFaceDetector().catch((err) => console.warn('Preload detector:', err));
  }, []);

  // Continuous real-time face detection loop on active webcam
  const runLiveFaceDetection = useCallback(async () => {
    if (!videoRef.current) return;
    if (videoRef.current.readyState < 2) {
      setFaceCheckMessage('Connecting camera feed...');
      return;
    }

    try {
      const result = await detectFaces(videoRef.current);
      setFaceCheckStatus(result.status);
      setFaceCheckMessage(result.message);
      setDetectedBox(result.box || null);
    } catch (e) {
      console.warn('Live detection error:', e);
      setFaceCheckStatus('READY');
      setFaceCheckMessage('Camera feed active');
    }
  }, []);

  const stopCamera = useCallback((keepVerifiedStatus = false) => {
    if (checkIntervalRef.current) {
      clearInterval(checkIntervalRef.current);
      checkIntervalRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    setIsCameraActive(false);

    // Only clear status if we are not keeping an already verified photo
    if (!keepVerifiedStatus && !photoVerified) {
      setFaceCheckStatus('IDLE');
      setFaceCheckMessage('Camera inactive');
    }
  }, [photoVerified]);

  const startCamera = async () => {
    setCameraError(null);
    setFaceCheckStatus('CHECKING');
    setFaceCheckMessage('Starting camera feed...');

    // 1. Check if navigator.mediaDevices is supported in current context
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      const isHttpNetwork =
        window.location.protocol !== 'https:' &&
        window.location.hostname !== 'localhost' &&
        window.location.hostname !== '127.0.0.1';
      if (isHttpNetwork) {
        setCameraError(
          'Mobile browsers block camera over plain HTTP Wi-Fi. Please open: https://' +
            window.location.host +
            ' (accept the security warning) or use "Upload Photo".'
        );
      } else {
        setCameraError(
          'Camera API is not supported in this browser window. Please check site permissions or try Chrome.'
        );
      }
      setIsCameraActive(false);
      setFaceCheckStatus('IDLE');
      return;
    }

    let stream = null;

    // 2. Attempt with preferred ideal constraints
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });
    } catch (primaryErr) {
      console.warn('Preferred camera constraints failed, attempting fallback { video: true }...', primaryErr);
      try {
        // Fallback: minimal camera constraints for basic/external webcams
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      } catch (fallbackErr) {
        console.error('All camera attempts failed:', fallbackErr);
        let errorMsg = 'Camera access blocked.';
        if (fallbackErr.name === 'NotAllowedError' || fallbackErr.name === 'PermissionDeniedError') {
          errorMsg =
            'Camera permission blocked. Click the lock/settings icon near your browser address bar and set Camera to "Allow", then try again.';
        } else if (fallbackErr.name === 'NotReadableError' || fallbackErr.name === 'TrackStartError') {
          errorMsg =
            'Camera is in use by another program (Zoom, Python script, or another tab). Close other camera apps and retry.';
        } else if (fallbackErr.name === 'NotFoundError' || fallbackErr.name === 'DevicesNotFoundError') {
          errorMsg = 'No camera hardware found on this computer/device.';
        } else if (fallbackErr.name === 'OverconstrainedError') {
          errorMsg = 'Camera does not support requested resolution.';
        } else {
          errorMsg = 'Camera error: ' + (fallbackErr.message || fallbackErr.name);
        }

        setCameraError(errorMsg);
        setIsCameraActive(false);
        setFaceCheckStatus('IDLE');
        return;
      }
    }

    streamRef.current = stream;
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
    }
    setIsCameraActive(true);

    // Start periodic face detection check (every 300ms)
    if (checkIntervalRef.current) clearInterval(checkIntervalRef.current);
    checkIntervalRef.current = setInterval(runLiveFaceDetection, 300);
  };

  // Ensure stream is attached to video element as soon as camera becomes active
  useEffect(() => {
    if (isCameraActive && streamRef.current && videoRef.current) {
      if (videoRef.current.srcObject !== streamRef.current) {
        videoRef.current.srcObject = streamRef.current;
      }
      videoRef.current.play().catch((err) => console.warn('Video play err:', err));
    }
  }, [isCameraActive]);

  useEffect(() => {
    return () => {
      stopCamera(false);
    };
  }, [stopCamera]);

  // Capture Photo with Face Validation
  const handleCapture = async () => {
    if (!videoRef.current) return;

    // Verify face is present before allowing capture!
    const verification = await detectFaces(videoRef.current);
    if (verification.status !== 'READY') {
      alert(`Cannot Capture: ${verification.message}\nMake sure student face is clearly visible.`);
      return;
    }

    const canvas = document.createElement('canvas');
    canvas.width = videoRef.current.videoWidth || 640;
    canvas.height = videoRef.current.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.9);

    setCapturedPhoto(dataUrl);
    setPhotoVerified(true);
    setFaceCheckStatus('READY');
    setFaceCheckMessage('Face successfully captured and verified!');
    stopCamera(true);

    if (navigator.vibrate) navigator.vibrate(35);
  };

  // Upload Photo File with Face Validation
  const handleFileUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const img = new Image();
      img.onload = async () => {
        setFaceCheckStatus('CHECKING');
        setFaceCheckMessage('Verifying uploaded photo for human face...');

        const result = await detectFaces(img);
        if (result.status !== 'READY') {
          alert(`Face Verification Failed: ${result.message}\nPlease select an image with a clear, single face.`);
          setCapturedPhoto(null);
          setPhotoVerified(false);
          setFaceCheckStatus('NO_FACE');
          setFaceCheckMessage('Invalid photo: No human face detected.');
          return;
        }

        setCapturedPhoto(event.target.result);
        setPhotoVerified(true);
        setFaceCheckStatus('READY');
        setFaceCheckMessage('Photo verified! 1 face detected.');
        stopCamera(true);
      };
      img.src = event.target.result;
    };
    reader.readAsDataURL(file);
  };

  const handleRetake = () => {
    setCapturedPhoto(null);
    setPhotoVerified(false);
    setFaceCheckStatus('CHECKING');
    setFaceCheckMessage('Starting camera feed...');
    startCamera();
  };

  // Submit Handler: Works seamlessly whether photo is captured OR live camera has face detected!
  const handleSubmit = async (e) => {
    e.preventDefault();

    // 1. Check all form inputs
    if (!studentId.trim() || !name.trim() || !className.trim() || !busId.trim()) {
      alert('Please fill out all required fields.');
      return;
    }

    // 2. Check Photo / Live Face
    let photoToSave = capturedPhoto;

    // If camera is open and live face is detected, auto-capture on submit!
    if (!photoToSave && isCameraActive && faceCheckStatus === 'READY' && videoRef.current) {
      const canvas = document.createElement('canvas');
      canvas.width = videoRef.current.videoWidth || 640;
      canvas.height = videoRef.current.videoHeight || 480;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);
      photoToSave = canvas.toDataURL('image/jpeg', 0.9);
      setCapturedPhoto(photoToSave);
      setPhotoVerified(true);
      stopCamera(true);
    }

    if (!photoToSave) {
      if (!isCameraActive) {
        startCamera();
        alert('Face Photo Required: Camera has been opened. Please position face in frame.');
      } else {
        alert('Position your face inside the circle until verified green, then click Save.');
      }
      return;
    }

    setIsSubmitting(true);
    try {
      await onStudentCreated(
        {
          student_id: studentId.trim(),
          name: name.trim(),
          class_name: className.trim(),
          bus_id: busId.trim(),
          is_active: true,
        },
        photoToSave
      );

      // Confetti celebration
      confetti({
        particleCount: 80,
        spread: 70,
        origin: { y: 0.65 },
        colors: ['#6366f1', '#10b981', '#06b6d4', '#f59e0b'],
      });

      if (navigator.vibrate) navigator.vibrate([40, 60, 40]);

      setSuccessToast(`Student "${name}" registered with verified face profile!`);
      setTimeout(() => setSuccessToast(null), 3800);

      // Reset form
      setName('');
      setCapturedPhoto(null);
      setPhotoVerified(false);
      setFaceCheckStatus('IDLE');
      setFaceCheckMessage('Camera inactive');
      setStudentId(suggestNextId());
    } catch (err) {
      alert('Failed to register student: ' + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Registration can proceed if:
  // 1) A photo has been captured/uploaded and verified, OR
  // 2) The live camera is actively detecting a verified face right now!
  const isFaceVerified = Boolean(capturedPhoto) || (isCameraActive && faceCheckStatus === 'READY');
  const isFaceMissing = isCameraActive && (faceCheckStatus === 'NO_FACE' || faceCheckStatus === 'MULTIPLE_FACES');

  return (
    <div>
      {/* Toast Alert */}
      {successToast && (
        <div className="toast-banner">
          <Sparkles size={18} color="var(--accent-emerald)" />
          <span>{successToast}</span>
        </div>
      )}

      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 800, color: '#fff' }}>Enroll New Student</h2>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          Biometric face verification is enforced before saving to central fleet cloud
        </p>
      </div>

      {/* Form Container */}
      <form onSubmit={handleSubmit} className="glass-card" style={{ padding: '20px' }}>
        {/* Photo Capture Section */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <label className="form-label" style={{ marginBottom: 0 }}>
              Face Verification (Mandatory) *
            </label>
            <span
              style={{
                fontSize: '0.72rem',
                fontWeight: 700,
                padding: '2px 8px',
                borderRadius: 999,
                background: isFaceVerified
                  ? 'rgba(16,185,129,0.18)'
                  : isFaceMissing
                  ? 'rgba(244,63,94,0.18)'
                  : 'rgba(255,255,255,0.06)',
                color: isFaceVerified
                  ? 'var(--accent-emerald)'
                  : isFaceMissing
                  ? 'var(--accent-rose)'
                  : 'var(--text-muted)',
                border: `1px solid ${
                  isFaceVerified
                    ? 'rgba(16,185,129,0.35)'
                    : isFaceMissing
                    ? 'rgba(244,63,94,0.35)'
                    : 'var(--border-subtle)'
                }`,
              }}
            >
              {isFaceVerified
                ? '✓ Face Verified'
                : faceCheckStatus === 'NO_FACE'
                ? '✗ No Face'
                : faceCheckStatus === 'MULTIPLE_FACES'
                ? '⚠ Multiple Faces'
                : 'Awaiting Face'}
            </span>
          </div>

          <div
            style={{
              width: '100%',
              height: 230,
              borderRadius: 18,
              background: '#040711',
              border: `2px dashed ${
                isFaceVerified
                  ? 'var(--accent-emerald)'
                  : isFaceMissing
                  ? 'var(--accent-rose)'
                  : 'var(--border-subtle)'
              }`,
              position: 'relative',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
              transition: 'border-color 0.3s ease',
            }}
          >
            {isCameraActive ? (
              <>
                <video
                  ref={(el) => {
                    videoRef.current = el;
                    if (el && streamRef.current && el.srcObject !== streamRef.current) {
                      el.srcObject = streamRef.current;
                      el.play().catch((e) => console.warn('play error:', e));
                    }
                  }}
                  autoPlay
                  playsInline
                  muted
                  onLoadedData={() => {
                    if (videoRef.current) {
                      videoRef.current.play().catch(() => {});
                    }
                    runLiveFaceDetection();
                  }}
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />

                {/* Face Target Guide Ring with Live Status Color */}
                <div
                  style={{
                    position: 'absolute',
                    width: 130,
                    height: 165,
                    borderRadius: '45%',
                    border: `2.5px solid ${
                      isFaceVerified
                        ? '#10b981'
                        : isFaceMissing
                        ? '#f43f5e'
                        : 'rgba(99,102,241,0.6)'
                    }`,
                    boxShadow: isFaceVerified
                      ? '0 0 25px rgba(16,185,129,0.5)'
                      : isFaceMissing
                      ? '0 0 25px rgba(244,63,94,0.4)'
                      : '0 0 15px rgba(99,102,241,0.3)',
                    pointerEvents: 'none',
                    transition: 'all 0.25s ease',
                  }}
                />

                {/* Floating Status Pill */}
                <div
                  style={{
                    position: 'absolute',
                    top: 12,
                    background: 'rgba(10,15,28,0.85)',
                    backdropFilter: 'blur(8px)',
                    padding: '4px 12px',
                    borderRadius: 999,
                    fontSize: '0.74rem',
                    fontWeight: 600,
                    color: isFaceVerified
                      ? 'var(--accent-emerald)'
                      : isFaceMissing
                      ? 'var(--accent-rose)'
                      : '#fff',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    border: '1px solid var(--border-subtle)',
                  }}
                >
                  {isFaceVerified ? (
                    <CheckCircle2 size={13} />
                  ) : (
                    <ShieldAlert size={13} />
                  )}
                  <span>{faceCheckMessage}</span>
                </div>

                {/* Capture Action Bar */}
                <div style={{ position: 'absolute', bottom: 12, display: 'flex', gap: 8 }}>
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={handleCapture}
                    disabled={faceCheckStatus !== 'READY'}
                    style={{
                      width: 'auto',
                      padding: '8px 20px',
                      borderRadius: 999,
                      fontSize: '0.84rem',
                      opacity: faceCheckStatus === 'READY' ? 1 : 0.5,
                      cursor: faceCheckStatus === 'READY' ? 'pointer' : 'not-allowed',
                      background:
                        faceCheckStatus === 'READY'
                          ? 'linear-gradient(135deg, #10b981, #059669)'
                          : 'rgba(255,255,255,0.1)',
                      borderColor: faceCheckStatus === 'READY' ? 'rgba(16,185,129,0.4)' : 'transparent',
                    }}
                  >
                    <Camera size={16} />
                    <span>{faceCheckStatus === 'READY' ? 'Capture Verified Face' : 'Show Face to Capture'}</span>
                  </button>

                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => stopCamera(false)}
                    title="Cancel Camera"
                    style={{ background: 'rgba(0,0,0,0.6)', borderRadius: 999 }}
                  >
                    <RotateCcw size={15} />
                  </button>
                </div>
              </>
            ) : capturedPhoto ? (
              <div style={{ width: '100%', height: '100%', position: 'relative' }}>
                <img
                  src={capturedPhoto}
                  alt="Verified Student"
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
                <div
                  style={{
                    position: 'absolute',
                    bottom: 12,
                    left: 12,
                    background: 'rgba(16,185,129,0.9)',
                    backdropFilter: 'blur(8px)',
                    color: '#fff',
                    padding: '4px 10px',
                    borderRadius: 999,
                    fontSize: '0.72rem',
                    fontWeight: 700,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 5,
                  }}
                >
                  <CheckCircle2 size={13} />
                  <span>Face Verified</span>
                </div>
                <button
                  type="button"
                  onClick={handleRetake}
                  title="Retake photo"
                  style={{
                    position: 'absolute',
                    top: 10,
                    right: 10,
                    background: 'rgba(0,0,0,0.7)',
                    border: '1px solid var(--border-subtle)',
                    color: '#fff',
                    borderRadius: '50%',
                    width: 34,
                    height: 34,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer',
                  }}
                >
                  <RotateCcw size={16} />
                </button>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 20 }}>
                <Scan size={36} color="var(--accent-primary)" style={{ margin: '0 auto 8px' }} />
                <h4 style={{ fontSize: '0.92rem', color: '#fff', marginBottom: 4 }}>
                  Face Photo Required
                </h4>
                <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 14 }}>
                  Camera uses on-device AI to verify human face before registering
                </p>
                <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={startCamera}
                    style={{ width: 'auto', padding: '9px 16px', fontSize: '0.82rem', borderRadius: 999 }}
                  >
                    <Camera size={15} />
                    <span>Open Camera</span>
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => fileInputRef.current?.click()}
                    style={{ width: 'auto', padding: '9px 16px', fontSize: '0.82rem', borderRadius: 999 }}
                  >
                    <ImageIcon size={14} style={{ marginRight: 5, display: 'inline' }} />
                    Upload Photo
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    style={{ display: 'none' }}
                    onChange={handleFileUpload}
                  />
                </div>
              </div>
            )}
          </div>

          {cameraError && (
            <p style={{ color: 'var(--accent-amber)', fontSize: '0.74rem', marginTop: 6 }}>
              {cameraError}
            </p>
          )}
        </div>

        {/* Inputs */}
        <div className="form-group">
          <label className="form-label">Student ID / Roll No *</label>
          <input
            type="text"
            className="form-input"
            value={studentId}
            onChange={(e) => setStudentId(e.target.value)}
            placeholder="e.g. 05 or STU-104"
            required
          />
        </div>

        <div className="form-group">
          <label className="form-label">Student Full Name *</label>
          <input
            type="text"
            className="form-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Aarav Sharma"
            required
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="form-group">
            <label className="form-label">Grade / Class *</label>
            <input
              type="text"
              className="form-input"
              value={className}
              onChange={(e) => setClassName(e.target.value)}
              placeholder="e.g. 5A"
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">Assigned Bus *</label>
            <select
              className="form-select"
              value={busId}
              onChange={(e) => setBusId(e.target.value)}
            >
              {buses.map((b) => (
                <option key={b.bus_id} value={b.bus_id}>
                  {b.bus_id} ({b.bus_name || 'Fleet Bus'})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Dynamic Action & Submit Button */}
        <div style={{ marginTop: 16 }}>
          {!isCameraActive && !capturedPhoto ? (
            <button
              type="button"
              className="btn-primary"
              onClick={startCamera}
              style={{
                width: '100%',
                background: 'linear-gradient(135deg, #6366f1, #4f46e5)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
              }}
            >
              <Camera size={18} />
              <span>Open Camera to Verify Face</span>
            </button>
          ) : (
            <button
              type="submit"
              className="btn-primary"
              disabled={isSubmitting || !isFaceVerified}
              style={{
                width: '100%',
                opacity: isFaceVerified ? 1 : 0.5,
                cursor: isFaceVerified ? 'pointer' : 'not-allowed',
                background: isFaceVerified
                  ? 'linear-gradient(135deg, #10b981, #059669)'
                  : 'rgba(255,255,255,0.08)',
                borderColor: isFaceVerified ? 'rgba(16,185,129,0.45)' : 'var(--border-subtle)',
                boxShadow: isFaceVerified ? '0 0 20px rgba(16,185,129,0.3)' : 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
              }}
            >
              {isFaceVerified ? <Check size={18} /> : <UserPlus size={18} />}
              <span>
                {isSubmitting
                  ? 'Registering to Cloud...'
                  : capturedPhoto
                  ? 'Save Verified Student'
                  : isCameraActive && faceCheckStatus === 'READY'
                  ? 'Capture & Save Student'
                  : 'Position Face in Frame to Register'}
              </span>
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
