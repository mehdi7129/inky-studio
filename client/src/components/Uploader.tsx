import { useCallback, useRef, useState, type RefObject } from 'react'
import { Icon } from './Icon'

interface UploaderProps {
  onFile: (file: File) => void
  disabled?: boolean
  inputRef?: RefObject<HTMLInputElement | null>
}

const ACCEPTED = ['image/jpeg', 'image/png', 'image/heic', 'image/heif', 'image/webp', '.heic', '.heif']

export function Uploader({ onFile, disabled = false, inputRef }: UploaderProps) {
  const [dragOver, setDragOver] = useState(false)
  const localInput = useRef<HTMLInputElement>(null)
  const fileInput = inputRef ?? localInput

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (disabled || !files || files.length === 0) return
      onFile(files[0])
    },
    [onFile, disabled],
  )

  return (
    <div
      className={`photo-uploader${dragOver && !disabled ? ' is-dragging' : ''}${disabled ? ' is-disabled' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        if (!disabled) setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragOver(false)
        handleFiles(event.dataTransfer.files)
      }}
    >
      <input
        ref={fileInput}
        type="file"
        accept={ACCEPTED.join(',')}
        className="uploader-file-input"
        aria-label="Choisir une photo"
        tabIndex={-1}
        disabled={disabled}
        onChange={(event) => {
          handleFiles(event.target.files)
          event.target.value = ''
        }}
      />
      <span className="uploader-icon"><Icon name="plus" size={24} /></span>
      <div>
        <h2>{disabled ? 'Votre photo se prépare.' : 'Une nouvelle vue ?'}</h2>
        <p>{disabled ? 'Ajustez son cadrage ci-dessous.' : 'Glissez une photo ici'}</p>
      </div>
      {!disabled && (
        <button type="button" className="bento-button bento-button-secondary" onClick={() => fileInput.current?.click()}>
          Choisir une photo
        </button>
      )}
      <span className="uploader-formats">JPEG, PNG, HEIC, WebP</span>
    </div>
  )
}
