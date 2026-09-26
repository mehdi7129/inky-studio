import { useEffect, useRef } from 'react'

interface PreviewCanvasProps {
  image: ImageData | null
  label: string
  className?: string
  aspectRatio?: number
}

export function PreviewCanvas({ image, label, className, aspectRatio = 5 / 3 }: PreviewCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !image) return
    canvas.width = image.width
    canvas.height = image.height
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.putImageData(image, 0, 0)
  }, [image])

  return (
    <figure className={['photo-preview', className ?? ''].join(' ')}>
      <figcaption>
        {label}
      </figcaption>
      <div className="photo-preview-surface" style={{ aspectRatio: image ? image.width / image.height : aspectRatio }}>
        {image ? (
          <canvas
            ref={canvasRef}
            role="img"
            aria-label={label}
          />
        ) : (
          <div className="photo-preview-waiting">
            Préparation de l’aperçu…
          </div>
        )}
      </div>
    </figure>
  )
}
