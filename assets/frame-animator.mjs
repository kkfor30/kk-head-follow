// Adapted from oil-motion interactive-motion.ts
                                    
                     
                        
                     
                      
                    
                          
                                  
  

                             
                                 
                                                                
                                      
                            
                  
  

const clamp = (value        , min        , max        ) =>
  Math.min(max, Math.max(min, value));

const wrap = (value        , length        ) =>
  ((value % length) + length) % length;

const shortestCircularDelta = (
  from        ,
  to        ,
  frameCount        ,
) => {
  let delta = wrap(to, frameCount) - wrap(from, frameCount);
  if (delta > frameCount / 2) delta -= frameCount;
  if (delta < -frameCount / 2) delta += frameCount;
  return delta;
};

const smoothDamp = (
  current        ,
  target        ,
  velocity        ,
  smoothTime        ,
  maxSpeed        ,
  deltaTime        ,
)                   => {
  const safeTime = Math.max(0.0001, smoothTime);
  const omega = 2 / safeTime;
  const x = omega * deltaTime;
  const decay = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x);
  const originalTarget = target;
  const maxChange = maxSpeed * safeTime;
  const change = clamp(current - target, -maxChange, maxChange);
  const limitedTarget = current - change;
  const temp = (velocity + omega * change) * deltaTime;
  let nextVelocity = (velocity - omega * temp) * decay;
  let nextPosition = limitedTarget + (change + temp) * decay;

  if (
    (originalTarget - current > 0) ===
    (nextPosition > originalTarget)
  ) {
    nextPosition = originalTarget;
    nextVelocity = 0;
  }
  return [nextPosition, nextVelocity];
};

export function createFrameAnimator(
  options                      ,
)                {
  const frameCount = Math.max(1, Math.floor(options.frameCount));
  const circular = options.circular ?? false;
  const smoothTime = options.smoothTime ?? 0.11;
  const maxSpeed = options.maxSpeed ?? frameCount * 2;
  const reducedMotion = options.reducedMotion ?? false;
  let position = clamp(options.initialFrame ?? 0, 0, frameCount - 1);
  let target = position;
  let velocity = 0;
  let lastFrame = -1;
  let lastTime = 0;
  let raf = 0;
  let destroyed = false;

  const normalizeFrame = (frame        ) =>
    circular
      ? wrap(frame, frameCount)
      : clamp(frame, 0, frameCount - 1);

  const render = () => {
    const frame = normalizeFrame(Math.round(position));
    if (frame !== lastFrame) {
      options.render(frame);
      lastFrame = frame;
    }
  };

  const loop = (now        ) => {
    raf = 0;
    if (destroyed) return;
    const deltaTime = lastTime
      ? Math.min((now - lastTime) / 1000, 1 / 30)
      : 1 / 60;
    lastTime = now;

    if (reducedMotion) {
      position = target;
      velocity = 0;
    } else {
      [position, velocity] = smoothDamp(
        position,
        target,
        velocity,
        smoothTime,
        maxSpeed,
        deltaTime,
      );
    }
    render();

    if (Math.abs(target - position) > 0.002 || Math.abs(velocity) > 0.002) {
      raf = requestAnimationFrame(loop);
    } else if (circular) {
      position = wrap(position, frameCount);
      target = position;
    }
  };

  const schedule = () => {
    if (!raf && !destroyed) raf = requestAnimationFrame(loop);
  };

  render();

  return {
    setTarget(frame        ) {
      const normalized = normalizeFrame(frame);
      target = circular
        ? position + shortestCircularDelta(position, normalized, frameCount)
        : normalized;
      schedule();
    },
    setDirection(x        , y        , startAngle = -Math.PI * 0.75) {
      const angle = Math.atan2(y, x);
      const turn = Math.PI * 2;
      const normalized = ((angle - startAngle + turn) % turn) / turn;
      this.setTarget(normalized * frameCount);
    },
    setProgress(progress        ) {
      this.setTarget(clamp(progress, 0, 1) * (frameCount - 1));
    },
    getCurrentFrame() {
      return normalizeFrame(position);
    },
    destroy() {
      destroyed = true;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    },
  };
}
