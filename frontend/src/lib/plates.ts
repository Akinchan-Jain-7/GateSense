/**
 * Display helpers for normalised plates ("UP16AB1234"). The backend stores plates without
 * spaces; people read them in groups, the way they're printed on the plate.
 */

const BH = /^(\d{2})(BH)(\d{4})([A-Z]{1,2})$/
const STANDARD = /^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{1,4})$/

export function formatPlate(plate: string): string {
  const bh = BH.exec(plate)
  if (bh) return `${bh[1] ?? ''} BH ${bh[3] ?? ''} ${bh[4] ?? ''}`
  const m = STANDARD.exec(plate)
  if (!m) return plate
  const [, state = '', district = '', series = '', number = ''] = m
  // Delhi puts a vehicle-class letter after the district: DL 1C AB 1234.
  if (state === 'DL' && series.length === 3) {
    return `DL ${district}${series[0] ?? ''} ${series.slice(1)} ${number}`
  }
  return [`${state}${district}`, series, number].filter(Boolean).join(' ')
}

/** What a guard types ("up 16 ab-1234") as the API expects it: letters and digits only. */
export function cleanPlateInput(text: string): string {
  return text.toUpperCase().replace(/[^A-Z0-9]/g, '')
}
