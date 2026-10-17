const short = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short' });
const full = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'long', year: 'numeric' });
const timestamp = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
export const shortDate = (value: number) => short.format(value);
export const fullDate = (value: number) => full.format(value);
export const dateTime = (value: number) => `${timestamp.format(value)} IST`;
