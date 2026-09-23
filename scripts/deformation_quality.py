"""Numerical checks for inverse pixel maps; never a visual quality certificate."""
import numpy as np


def inspect_inverse_map(mapping, region, protected=None, minimum_jacobian=.2):
    mapping=np.asarray(mapping)
    region=np.asarray(region,dtype=bool)
    if mapping.ndim!=3 or mapping.shape[2]!=2 or mapping.shape[:2]!=region.shape or min(region.shape)<2:
        raise ValueError('map and region dimensions mismatch')
    if not np.isfinite(mapping).all() or not region.any():
        raise ValueError('map must be finite and inspected region nonempty')
    if not 0<minimum_jacobian<=1:raise ValueError('invalid Jacobian threshold')
    h,w=region.shape
    gx=np.gradient(mapping[:,:,0]);gy=np.gradient(mapping[:,:,1])
    det=gx[1]*gy[0]-gx[0]*gy[1]
    folded=int(np.count_nonzero(det[region]<=minimum_jacobian))
    outside=int(np.count_nonzero(region & ((mapping[:,:,0]<0)|(mapping[:,:,0]>w-1)|(mapping[:,:,1]<0)|(mapping[:,:,1]>h-1))))
    yy,xx=np.mgrid[:h,:w]
    shift=np.linalg.norm(mapping-np.dstack([xx,yy]),axis=2)
    protected_shift=0.
    if protected is not None:
        protected=np.asarray(protected,dtype=bool)
        if protected.shape!=region.shape:raise ValueError('protected mask dimensions mismatch')
        if protected.any():protected_shift=float(shift[protected].max())
    return dict(passed=not folded and not outside and protected_shift<=1e-5,
                foldedPixels=folded,outsidePixels=outside,minimumJacobian=float(det[region].min()),
                maxDisplacement=float(shift[region].max()),protectedDisplacement=protected_shift,
                visualStatus='unreviewed')
