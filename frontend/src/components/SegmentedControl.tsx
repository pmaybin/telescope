import { useId } from 'react'

type Option = { value: string; label: string }

/** Radio group styled as a segmented control. */
export function SegmentedControl({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: Option[]
  onChange: (value: string) => void
}) {
  const id = useId()
  return (
    <div className="field">
      <span className="field-label" id={`${id}-label`}>
        {label}
      </span>
      <div
        className="segmented"
        role="radiogroup"
        aria-labelledby={`${id}-label`}
      >
        {options.map((o) => (
          <label key={o.value}>
            <input
              type="radio"
              name={id}
              value={o.value}
              checked={value === o.value}
              onChange={() => onChange(o.value)}
            />
            {o.label}
          </label>
        ))}
      </div>
    </div>
  )
}
