namespace ScoutMind.FMReader.Discovery;

/// <summary>
/// 把“当前存档身份解析结果”收敛为可供 Verified 门控比较的指纹。
///
/// 只有唯一且来自存档文件的指纹才能作为当前身份；歧义、未解析或非文件来源一律返回 <c>null</c>，
/// 让门控按“缺少当前存档身份”拒绝 Mark(Verified)，而不是沿用调用方传入的历史指纹。
/// </summary>
public static class SaveIdentityBinding
{
    /// <summary>取当前存档指纹；无法唯一确定时返回 <c>null</c>。</summary>
    /// <param name="resolution">本次解析结果。</param>
    /// <returns>形如 <c>si:v1:file:&lt;sha256&gt;</c> 的指纹，或 <c>null</c>。</returns>
    public static string? CurrentFingerprint(SaveIdentityResolution resolution)
    {
        ArgumentNullException.ThrowIfNull(resolution);
        if (resolution.IsAmbiguous || !resolution.CurrentSaveConfirmed)
        {
            return null;
        }

        if (resolution.Kind is not (SaveIdentityKind.SaveFile or SaveIdentityKind.UserConfirmed))
        {
            return null;
        }

        return resolution.Fingerprint.StartsWith("si:v1:file:", StringComparison.Ordinal)
            ? resolution.Fingerprint
            : null;
    }
}
