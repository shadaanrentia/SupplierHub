export const activeStatus=status=>['queued','planning','running','stopping','in_progress'].includes(status);
export function progressJob(jobs,detail,hidden=[]){return jobs.map(job=>detail?.id===job.id&&activeStatus(job.status)?{...job,...detail}:job).find(job=>activeStatus(job.status)&&!hidden.includes(job.id))||null;}
export function progressPercent(data){const total=Number(data?.total)||0;if(!total||!data?.counts)return null;return Math.max(0,Math.min(100,Math.round(((Number(data?.counts?.details_processed)||0)+(Number(data?.counts?.finished)||0))*50/total)));}
