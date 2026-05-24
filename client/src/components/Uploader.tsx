import { useCallback, useRef, useState } from 'react'

interface UploaderProps {
  onFile: (file: File) => void
  disabled?: boolean
}

const ACCEPTED = ['image/jpeg', 'image/png', 'image/heic', 'image/heif', 'image/webp']

export function Uploader({ onFile, disabled }: UploaderProps) {
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return
      const file = files[0]
      onFile(file)
    },
    [onFile],
  )

  return (
    <div
      className={[
        'rounded-xl border-2 border-dashed transition-all',
        'flex flex-col items-center justify-center gap-3',
        'p-10 text-center cursor-pointer',
        dragOver
          ? 'border-indigo-500 bg-indigo-50/50 dark:bg-indigo-900/20'
          : 'border-neutral-300 dark:border-neutral-700 hover:border-neutral-400 dark:hover:border-neutral-600',
        disabled ? 'opacity-50 pointer-events-none' : '',
      ].join(' ')}
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        handleFiles(e.dataTransfer.files)
      }}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED.join(',')}
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
      <div className="text-3xl" aria-hidden="true">📷</div>
      <div>
        <p className="font-medium text-neutral-700 dark:text-neutral-200">
          Glisse une photo ici
        </p>
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
          JPEG, PNG, HEIC, WebP — sera convertie pour ton écran
        </p>
      </div>
    </div>
  )
}
