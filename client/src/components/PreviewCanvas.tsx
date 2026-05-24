import { useEffect, useRef } from 'react'

interface PreviewCanvasProps {
  image: ImageData | null
  label: string
  className?: string
}

export function PreviewCanvas({ image, label, className }: PreviewCanvasProps) {
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
    <figure className={['flex flex-col gap-2', className ?? ''].join(' ')}>
      <figcaption className="text-xs uppercase tracking-wider text-neutral-500">
        {label}
      </figcaption>
      <div className="aspect-[5/3] bg-neutral-200 dark:bg-neutral-800 rounded-lg overflow-hidden border border-neutral-300 dark:border-neutral-700">
        {image ? (
          <canvas
            ref={canvasRef}
            className="w-full h-full object-contain"
            style={{ imageRendering: 'pixelated' }}
            aria-label={label}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-sm text-neutral-500">
            (en attente)
          </div>
        )}
      </div>
    </figure>
  )
}
